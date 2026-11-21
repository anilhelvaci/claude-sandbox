# claude-sandbox

Run a fleet of Claude Code agents in an Ubuntu container, on a dedicated clone of a
project, behind an outbound firewall. You edit the clone from your Mac as usual; each
agent gets its own git worktree and tmux window. Optionally, a task runs as a
test-first **team** (tester, builder, reviewer) whose every handoff is checked by
deterministic gates.

It's built on Anthropic's reference devcontainer (`anthropics/claude-code/.devcontainer`).
The firewall and the "sudo only for the firewall" trick come from there; the Ubuntu
base, dedicated clones, worktrees, tmux fleet and teams are added here.

Everything is Python 3 (standard library only). Every command explains itself:
`sbx help`, `sbx help <command>` or `sbx <command> --help`, and the same for `bus`,
`gate`, `panel`, `proxy` and `role-prompt` inside the container.

- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [How it fits together](#how-it-fits-together)
- [Working with independent agents](#working-with-independent-agents)
- [Teams: tester, builder, reviewer](#teams-tester-builder-reviewer)
- [Bringing work back](#bringing-work-back)
- [Firewall](#firewall)
- [Command reference](#command-reference)
- [Configuration reference](#configuration-reference)
- [Files and layout](#files-and-layout)
- [Development](#development)
- [Safety model](#safety-model)
- [Upgrading from the shell-script version](#upgrading-from-the-shell-script-version)

## Requirements

- Docker (Docker Desktop on macOS).
- git 2.38 or newer on the host (`sbx merge` uses `git merge-tree --write-tree`).
- Python 3.9 or newer on the host. The macOS system `python3` works. The container
  brings its own.

## Quickstart

```sh
alias sbx=~/claude-sandbox/sbx

sbx build                                   # once (and again to update Claude Code)
sbx new proto ~/code/some-repo          # clone + start container (firewall on)
sbx login proto                             # once; the login is shared by all sandboxes
sbx agent proto api "build the REST API"    # agent on branch agent/api in .worktrees/api
sbx agent proto ui  "build the frontend"
sbx attach proto                            # watch: Ctrl-b <n> switch window, Ctrl-b d detach
```

`sbx new` ends by printing these next steps, so you don't need to memorize them.

## How it fits together

```
Mac (host)                                      container sbx-<name> (Ubuntu)
──────────                                      ─────────────────────────────
sbx  ── docker exec ──────────────────────────► tmux session "fleet"
                                                  ├─ window "shell"
~/sandboxes/<name>/                      ├─ window "api"            claude (agent)
  repo/              ◄── same path, mounted ──►   ├─ window "vault-tester"   claude + bus/gate
    .worktrees/<task>    (you and the agents      ├─ window "vault-builder"
    .git/sbx/<task>/     see each other's edits)  ├─ window "vault-reviewer"
  project/  (config, notes, skills)  ── ro ──►    └─ window "proxy"          proxy loop
  allowlist/ (extra domains)         ── ro ──►
claude-sandbox/bin, roles, skills    ── ro ──►  /opt/sbx/{bin,roles,skills}
```

- A **sandbox** is a clone of your project (`$SBX_HOME/<name>/repo`, default
  `~/sandboxes/<name>/repo`) plus one container, `sbx-<name>`. The clone is
  mounted at the same absolute path inside, so git worktree paths work on both sides.
- An **agent** is Claude Code in a tmux window of the sandbox's `fleet` session. With a
  task name it works in its own worktree, `.worktrees/<task>`, on branch `agent/<task>`.
- The container is the permission boundary: agents run with
  `--dangerously-skip-permissions`, have no general sudo, and see only their clone and
  the read-only mounts.
- Any `sbx` command that needs the container starts it if it's stopped, re-applies the
  firewall (failing closed: no firewall, no sandbox), and recreates the tmux session.

## Working with independent agents

1. **Create the sandbox.** `sbx new proto ~/code/some-repo [branch]` clones the repo
   and starts the container (building the image first if needed). When the source is a
   local repo, the clone's `origin` becomes `host` (that's where `sbx merge` brings work
   back), and a new `origin` points at your repo's own upstream, for fetching only. There
   are no git credentials inside.
2. **Log in once.** `sbx login proto` opens Claude Code. Log in, then exit. The login lives
   in a Docker volume shared by every sandbox.
3. **Start agents.** `sbx agent proto api "build the REST API"` creates `.worktrees/api` on
   branch `agent/api` (or reuses it) and starts claude there with your prompt. Anything
   after the task goes to claude, e.g. `--model opus`. Omit the task to work in the main
   checkout. When claude exits, the window drops to a bash shell so you can see what
   happened.
4. **Watch and steer.** `sbx attach proto` puts you in the fleet: `Ctrl-b <n>` or
   `Ctrl-b w` switches windows, `Ctrl-b d` detaches (the agents keep running). Open
   `~/sandboxes/proto/repo` in your editor; you and the agents see each other's
   edits live.
5. **Run things.** `sbx shell proto` is a shell as the agents' user, for running the
   clone's code sandboxed. `sbx root proto` is root, e.g. for `apt-get install`.
   Dev servers on ports 3000, 5173, 8000 and 8545 are published on 127.0.0.1 at random
   host ports; `sbx ports proto` shows where.
6. **Finish.** Bring the work back (see [Bringing work back](#bringing-work-back)).
   `sbx stop proto` stops the container, and `sbx rm proto` removes it while keeping
   the clone. `sbx ls` lists every sandbox with its state.

## Teams: tester, builder, reviewer

Instead of independent agents, a task can run as a test-first team, adapted from garden's
assayer, builder and jury panel:

```sh
sbx skills proto add x-ray fizz solidity-auditor   # stack skills this sandbox's agents see
$EDITOR ~/sandboxes/proto/project/config  # gate commands, test paths, seats, skills per role
sbx tdd proto vault "implement docs/vault-spec.md"  # tester + builder + reviewer on .worktrees/vault
sbx inbox proto                                    # escalations and "done" reports for you
sbx bus proto vault status                         # whose turn, round, last panel
```

The three agents share one worktree and take turns. Only the holder of the turn
changes files:

```
tester: failing tests ──► builder: make them pass ──► reviewer: panel ──► pass: next slice
                                     ▲                     │
                                     └── changes ──────────┘   (missing tests go back to the tester)
```

### What you'll see

- `sbx tdd` opens three windows: `vault-builder` and `vault-reviewer` read the bus and
  wait, and `vault-tester` holds the first turn with your spec. If the config says
  `proxy = on`, a `proxy` window starts too.
- Each handoff prints the gate's transcript (`ok` / `FAIL` per check). When a check
  fails, the handoff is **refused** and nothing changes. When all pass, the next agent's
  window gets a line typed into it, `[bus] handoff from tester: run 'bus read'`, which
  wakes it up.
- Messages for you collect in your inbox: escalations, the tester's "done" report,
  reviewer overrides and proxy reports. `sbx inbox proto` shows the unread ones from
  every task.
- `sbx bus proto vault status` shows whose turn it is (since when and why), the cycle's
  base and round, the red tests, the proxy's budget, unread counts and the last panel
  verdict. `sbx bus proto vault log` shows the full event history.

### The pieces

- **Roles** (`roles/`) are generic. The tester edits tests only, the builder edits
  production code only, and the reviewer edits nothing and runs `panel`, which fans out
  one `claude -p` per juror seat (`roles/jurors/`: prover, saboteur, breaker,
  corner-prober). Shared disciplines are in `skills/`. `role-prompt <role>` prints exactly
  what an agent is told.
- **Specialization** is per sandbox, in `$SBX_HOME/<name>/project/`, created from
  `templates/project/` on first start. `config` holds the gate commands, `test_paths`,
  `protected` and `scratch` paths, seats and `skills.<role>`. The notes in `tester.md`,
  `builder.md` and `reviewer.md` are appended to each role's prompt. `project/skills/` is
  mounted over `~/.claude/skills`, so each sandbox sees only the skills you gave it
  (`sbx skills <name> add|rm|ls`, copied from `~/.claude/skills`).
- **The bus** (`bin/bus`) is a set of file inboxes under the clone's `.git/sbx/<task>/`,
  shared by every worktree and ignored by git. `bus send` talks without passing the turn,
  and `bus handoff` passes it.
- **The gate** (`bin/gate`) decides every handoff, with no LLM involved:

  | Transition | The gate requires |
  |---|---|
  | tester → builder | clean tree; the tester touched only test paths; each new or changed test file **fails** (`red`), or passes with `--defensive "<why>"` |
  | builder → reviewer | clean tree; no test paths touched; build, suite and checks pass (`green`); with the production changes reverted, the cycle's tests fail again (`prover`) |
  | reviewer → tester (pass) | the panel passed on this exact HEAD, or `--override "<why>"` (copied to you) |
  | reviewer → builder or tester | `--review <findings file>`; counts one round |
  | builder → tester | as builder → reviewer, only when the config has `seats = none` |
  | anyone → maintainer | always allowed (`bus escalate`); past `max_rounds` the bus escalates by itself |
  | maintainer → anyone | always allowed, with no gate |

  Agents can run any check early: `gate red`, `gate green`, `bus handoff builder --dry-run`.
- **Chores** (docs or config work, with no tests to write):
  `sbx bus <name> <task> handoff builder --chore "<what>"`. The builder still has to pass
  `green`, and the panel still reviews, but there's no red phase and no prover. The
  reviewer's pass gives the turn back to you, and findings go back to the builder.
- **You can step in at any point.** `sbx bus <name> <task> handoff <role> "..."` hands the
  turn to a role with no gate. `sbx bus <name> <task> done "<note>"` releases the task as
  done; if an agent held the turn, it's told to stop. An open cycle is kept, so handing
  the turn back later resumes it.
- **The proxy** (`roles/proxy.md`, `bin/proxy`), adapted from garden's. With
  `proxy = on` in the config (off by default), an escalation or round limit that has
  waited `proxy_grace` seconds goes to one `claude -p` that stands in for you. It decides
  direction and hands the turn to a role with binding instructions, or defers what's
  beyond it: finishing or descoping, the rules and gates, the spec, anything destructive
  or outside the sandbox. It never acts on the tester's `bus done`, makes at most
  `proxy_max` decisions per task (`unlimited` for no cap), and reports each one to your
  inbox (with the commands to override it) and to `.git/sbx/<task>/proxy-decisions.md`.
  `sbx tdd` starts it when it's on; `sbx proxy <name>` starts it by hand. Put your
  standing preferences for it in `project/proxy.md`.
- **Findings** use `path:line: [must-fix|should-fix|comment] (seat) message`, so VS Code
  problem matchers and vim's quickfix list can jump to them.

All of `bin/`, `roles/`, `skills/` and `project/` are mounted read-only: agents can't
edit their roles, the gate or its config.

Echidna and Medusa aren't in the image yet. Slither is (`--build-arg WITH_SLITHER=0` to
leave it out, `--build-arg SLITHER_VERSION=x.y.z` to pin it).

## Bringing work back

For a finished team task, `sbx merge <name> <task>` puts the work on the task's own branch
in the repo the sandbox was cloned from. The branch defaults to the task's name; use
`--branch <b>` for another. It creates the branch, fast-forwards it, or builds a merge
commit, all without a checkout, so that repo's working tree and uncommitted changes are
never touched. It never pushes.

What you see: the plan (`create`, `fast-forward` or `merge`), the commits and a diffstat,
then `Apply (...) to branch ... ? [y/N]`. Use `--yes` to skip the question. It refuses
when:

- the task isn't done (the tester's `bus done`, a passed chore, or your own release).
  `--force` merges anyway.
- the task's worktree has uncommitted changes. `--force` leaves them behind.
- that branch is checked out in your repo. Pick another with `--branch`.
- the merge would conflict. It lists the files and suggests `--branch <task>-2`.

Each merge is logged in `.git/sbx/<task>/log`.

By hand, for any agent's branch (the container has no git credentials and can't push),
from your real repo:

```sh
git fetch ~/sandboxes/proto/repo agent/api
git log -p ..FETCH_HEAD        # review
git merge FETCH_HEAD           # or cherry-pick
```

## Firewall

On by default. Outbound traffic is limited to DNS, GitHub (its published IP ranges) and
the domains in the allowlist files. Everything else is rejected, including services on
your Mac. There's no IPv6 egress at all.

- All sandboxes: edit `allowlist/default.txt`.
- One sandbox: add `~/sandboxes/<name>/allowlist/<anything>.txt`.
- Apply the change: `sbx firewall <name>`. This also re-resolves IPs; run it if a host
  that worked starts failing after a few hours (CDN IPs rotate). It prints each allowed
  domain with its addresses, then verifies that example.com is blocked and that GitHub
  and Anthropic are reachable.
- Without the firewall: `SBX_FIREWALL=0 sbx new ...`. The setting sticks to the sandbox:
  it's stored in `sandboxes/<name>/firewall`, and changing it takes `sbx rm` and starting
  again.

The script is `init-firewall`, installed in the image at `/usr/local/bin/init-firewall`.
Agents may rerun it through sudo (with no arguments, and nothing else), but they can't
change the allowlist or the rules: both are mounted read-only and owned by root.

## Command reference

Every command has its own help: `sbx help <command>` or `sbx <command> --help`.

### On your Mac: `sbx`

| Command | What it does |
|---|---|
| `sbx build [docker build args]` | Build the image (again, to update Claude Code), e.g. `--build-arg WITH_FOUNDRY=0` |
| `sbx new <name> <src> [branch]` | Clone `<src>` into `$SBX_HOME/<name>/repo` and start its container |
| `sbx login <name>` | Start claude to log in (once; the login is shared by all sandboxes) |
| `sbx agent <name> [task] [--role R] [claude args...]` | Start an agent in a tmux window, in `.worktrees/<task>` on `agent/<task>` (no task: the main checkout). `--role tester\|builder\|reviewer` joins the task's team |
| `sbx tdd <name> <task> <spec>` | Start a tester, builder and reviewer team on one task |
| `sbx bus <name> <task> <bus args>` | The task's bus, as the maintainer (`status`, `read`, `send`, `handoff`, `done`, `log`) |
| `sbx inbox <name>` | Your unread messages from every team |
| `sbx proxy <name>` | Start the proxy (it acts only while the config says `proxy = on`) |
| `sbx skills <name> [ls \| add <skill>... \| rm <skill>...]` | The stack skills this sandbox's agents see, copied from `$SBX_SKILLS_SRC` |
| `sbx merge <name> <task> [--branch B] [--yes] [--force]` | Put a finished task's work on its own branch in the repo you cloned from |
| `sbx attach <name>` | Attach to the fleet's tmux session (detach: `Ctrl-b d`) |
| `sbx shell <name>` | bash in the container as the agents' user |
| `sbx root <name>` | root bash in the container (`apt-get install` etc.) |
| `sbx firewall <name>` | Re-apply the firewall (after editing an allowlist, or to refresh IPs) |
| `sbx ports <name>` | Show which host ports the dev ports landed on |
| `sbx ls` | List sandboxes: name, container state, firewall, clone |
| `sbx stop <name>` | Stop the container |
| `sbx rm <name>` | Remove the container and its cache volume; the clone is kept |

### Inside the container (used by agents, and by you through `sbx bus` or `sbx shell`)

| Command | What it does |
|---|---|
| `bus send <to> [-k kind] [text \| -]` | Drop a message in a role's inbox (doesn't pass the turn) |
| `bus read` | Print your unread messages and mark them read |
| `bus wait [seconds]` | Block until you have mail (default 540s; exit 1 on timeout) |
| `bus handoff <to> [--defensive why \| --review file \| --override why \| --chore \| --dry-run] [text \| -]` | Pass the turn, through the gate for the transition |
| `bus escalate [text \| -]` | Give the turn to the maintainer |
| `bus done [text \| -]` | Tester: the spec is covered. Maintainer: release the task |
| `bus status` / `bus log` / `bus init` | State of the task, its event log, start it |
| `gate clean` | Every change is committed |
| `gate paths <role> [base]` | The role touched only what it owns |
| `gate red [base]` / `gate defensive [base]` | Each new or changed test file fails / passes |
| `gate green` | Build, the full suite and every check pass |
| `gate prover <base> <file>...` | With production changes reverted, the tests fail again |
| `panel [base]` | Run the reviewer seats; verdict `pass` (exit 0), `changes` (3) or `error` (1) |
| `proxy loop [seconds]` / `proxy tick` | The proxy's watch loop, or one pass |
| `role-prompt <role>` | Print a role's full system prompt |

Who you are on the bus comes from `SBX_ROLE` and `SBX_TASK`; `sbx agent --role` and
`sbx bus` set them.

## Configuration reference

### Project config: `$SBX_HOME/<name>/project/config`

The format is `key = value`, one per line. A key may repeat, and `#` starts a comment
only at the start of a line. Edits take effect immediately. See
`templates/project/config` for a commented example, including TypeScript and Python
setups.

| Key | Meaning |
|---|---|
| `stack` | A name for the stack, shown to agents and seats (default `generic`) |
| `test_paths` | Paths the tester owns. Ending in `/` means a prefix; otherwise a glob (`*` crosses `/`) |
| `protected` | Paths no agent may change |
| `scratch` | Paths the gate ignores (agent notes, reports) |
| `build`, `test`, `check` | `gate green`: build (optional), the full suite (required), then each `check` |
| `test_only` | Runs only the given test files; must contain `{file}` (each file on its own) or `{files}` (all together) |
| `seats` | Juror seats from `roles/jurors/`, or `none` for no reviewer (default: all four) |
| `seat_model`, `seat_timeout` | Model and timeout in seconds (default 900) for each seat |
| `max_rounds` | Review rounds per cycle before escalating to you (default 4) |
| `proxy`, `proxy_grace`, `proxy_max`, `proxy_timeout` | The proxy: `on`/`off` (default off), seconds to wait for you first (600), decisions per task (3, or `unlimited`), its timeout (900) |
| `skills.tester`, `skills.builder`, `skills.reviewer` | Skills (by directory name) each role is told to use |

Next to it: `tester.md`, `builder.md` and `reviewer.md` (notes for each role; the
reviewer's also go to every panel seat), `proxy.md` (your standing preferences for the
proxy), and `skills/` (managed with `sbx skills`).

### Environment variables (host)

| Variable | Default | Meaning |
|---|---|---|
| `SBX_HOME` | `~/sandboxes` | Where sandboxes live |
| `SBX_IMAGE` | `claude-sandbox:latest` | The image to build and run |
| `SBX_PORTS` | `3000 5173 8000 8545` | Container ports to publish on 127.0.0.1 (set before `sbx new`) |
| `SBX_MEMORY`, `SBX_CPUS` | `8g`, `6` | Container limits |
| `SBX_FIREWALL` | `1` | `0` creates a sandbox without the firewall |
| `SBX_CONFIG_VOLUME` | `claude-sandbox-config` | The Docker volume holding the shared Claude login |
| `SBX_SKILLS_SRC` | `~/.claude/skills` | Where `sbx skills add` copies from |

Inside the container: `SBX_BUS_NUDGE=0` stops the bus from typing wake-up lines into
windows, and `PROXY_MODEL` picks the proxy's model.

## Files and layout

```
claude-sandbox/
  sbx                  the host CLI (Python)
  Dockerfile           the image
  init-firewall        the firewall script (Python; runs as root in the container)
  allowlist/           domains every sandbox may reach
  bin/                 mounted at /opt/sbx/bin (on the agents' PATH)
    bus gate panel proxy role-prompt
    sbx_lib.py         shared helpers: config, bus state, path classes
    sbx_cli.py         the subcommand/help dispatcher shared by sbx, bus, gate, proxy
  roles/               role briefs (COMMON, tester, builder, reviewer, proxy, jurors/)
  skills/              shared disciplines (regression evidence, adversarial tests)
  templates/project/   the starting project config and role notes

$SBX_HOME/<name>/
  repo/                the clone (.worktrees/<task> for each task)
  repo/.git/sbx/<task>/
    inbox/<role>/{unread,read}/   messages
    state/                        turn, bases, round, cycle tests, proxy counters
    log                           event log
    reviews/<time>/, reviews/latest   panel runs (seat outputs, findings.txt, verdict)
    gate/                         gate logs
    proxy-decisions.md            every proxy decision
  project/             config, role notes, proxy.md, skills/
  allowlist/           this sandbox's extra domains
  firewall             1 or 0, fixed at creation
```

## Development

Lint and formatting use [Ruff](https://docs.astral.sh/ruff/), configured in
`pyproject.toml` (Python 3.9 target, 120 columns; it includes the extensionless scripts).
With `uv` installed there's nothing else to install:

```sh
uvx ruff check .          # unused imports, undefined names, import order, outdated syntax, likely bugs
uvx ruff check --fix .    # apply the safe fixes
uvx ruff format .         # format
uvx pyright sbx init-firewall bin/*   # type check (what Pylance shows; basedpyright works too)
```

`pyproject.toml` also tells Pyright, Pylance and basedpyright that `bin/` is an import
path (so the IDE resolves `sbx_lib` and `sbx_cli`), and sets the checking level to
`standard`. basedpyright's own default is its strictest mode, which flags every call
whose result goes unused, such as `f.write(...)` or `subprocess.run(...)`.

Keep the code runnable on Python 3.9 (macOS's system `python3`) and standard-library only.

## Safety model

**Protected:**
- Your Mac's files, including `~`, other repos, `~/.ssh`, `~/.aws` and keys. The container
  only sees its clone.
- Your real repo. The clone is a separate copy.
- Arbitrary network egress, when the firewall is on.
- Git config and hooks in the clone's `.git`, which are read-only to agents. Your Mac's
  git and editor run these, so an agent can't plant a hook or `core.fsmonitor` there.

**Not protected:**
- **The network, when the firewall is off.** The agent could upload the clone or the Claude
  token anywhere.
- **The firewall's limits.** DNS is open, so data could be smuggled out through lookups.
  The allowlist is IP-based, and CDN IPs (GitHub raw, npm) are shared with other sites.
  GitHub is fully reachable, so an agent could push to a public repo it creates with its
  own means. There are no credentials for that inside, but the destination is open.
- **Secrets committed in the repo.** Anything in the clone is readable by the agents. Check
  for `.env` files, keys and fixtures before cloning in.
- **The clone itself.** Agents can delete or rewrite it and its history. Your real repo is
  unaffected.
- **Anything you mount or paste in.** A token, `~/.ssh` or the Docker socket each give the
  agent that thing.
- **Running the clone's code on your Mac.** The clone is agent-written code. Running
  `npm install`, `forge test`, `make` or VS Code tasks from it on the Mac runs that code
  unsandboxed. Use `sbx shell` for that. Also, agents can create files the read-only
  mounts don't cover, such as a nested `.git/` directory with its own config, or a
  `.vscode/` folder. Open the clone in your editor's restricted mode, or review work by
  fetching it into your real repo as shown above.

## Upgrading from the shell-script version

The Python scripts read and write the same files and state (`.git/sbx/<task>/`,
`project/config`, inboxes, logs), so tasks in flight carry on. `bin/` is mounted live,
so running containers pick up the new `bus`, `gate`, `panel`, `proxy` and `role-prompt`
at once.

The firewall script is now `/usr/local/bin/init-firewall` (it was `init-firewall.sh`),
and it's baked into the image. Rebuild and recreate each sandbox once:

```sh
sbx build
sbx rm <name>        # the clone, its tasks and its config are kept
sbx attach <name>    # any command recreates the container from the new image
```

Until you do, a firewalled sandbox on the old image fails closed when it restarts:
`sbx` stops the container with "firewall failed".

A sandbox created before teams existed also needs that `sbx rm` to get the roles, bus
and gate mounts.
