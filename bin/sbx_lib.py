"""Shared helpers for bus, gate, panel, proxy and role-prompt.

These run INSIDE the container. The project config and the role/skill library
are mounted read-only, so an agent can't weaken its own gates.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

SBX_ROOT = Path(os.environ.get("SBX_ROOT") or "/opt/sbx")  # roles/, skills/, bin/ (from claude-sandbox)
SBX_PROJECT = Path(
    os.environ.get("SBX_PROJECT") or "/etc/sbx/project"
)  # config + per-role notes (from $SBX_HOME/<name>/project)


# ---- basics -----------------------------------------------------------------


def die(message: str) -> NoReturn:
    """Print '<program>: <message>' to stderr and exit 1."""
    print(f"{os.path.basename(sys.argv[0])}: {message}", file=sys.stderr)
    sys.exit(1)


def now() -> str:
    """UTC timestamp for logs and messages, e.g. 2026-10-30T09:27:51Z."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def stamp() -> str:
    """Compact UTC timestamp for file names, e.g. 20261030T092751Z."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def split_lines(text: str) -> list[str]:
    """Split text into lines the way line-oriented shell tools see them."""
    if not text:
        return []
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    return lines


def read_text(path: Path, default: str = "") -> str:
    """A file's content with trailing newlines removed (like "$(cat file)"), or default."""
    try:
        return path.read_text().rstrip("\n")
    except OSError:
        return default


def sh(*cmd: str, stdin: str | None = None, quiet: bool = False, check: bool = True) -> str:
    """Run a command and return its stdout without trailing newlines.

    stderr goes to the terminal (or nowhere with quiet=True). With check=True a
    failing command ends this program with the command's exit code, as 'set -e'
    did in the shell versions.
    """
    proc = subprocess.run(
        cmd,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else None,
    )
    if check and proc.returncode != 0:
        sys.exit(proc.returncode)
    return proc.stdout.rstrip("\n")


def succeeds(*cmd: str) -> bool:
    """Run a command silently; True if it exited 0."""
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def git(*args: str, quiet: bool = False, check: bool = True) -> str:
    return sh("git", *args, quiet=quiet, check=check)


# ---- project config ---------------------------------------------------------
# "key = value" lines; '#' starts a full-line comment; a key may repeat (e.g.
# several 'check' lines). conf_all returns every value, conf_get the first.


def conf_all(key: str) -> list[str]:
    config = SBX_PROJECT / "config"
    if not config.is_file():
        return []
    prefix = re.compile(r"^\s*" + re.escape(key) + r"\s*=\s*")
    values = []
    for line in split_lines(config.read_text()):
        m = prefix.match(line)
        if m:
            values.append(line[m.end() :].rstrip())
    return values


def conf_get(key: str, default: str = "") -> str:
    values = conf_all(key)
    return (values[0] if values else "") or default


# ---- task and bus location --------------------------------------------------


def task_name() -> str:
    """The task is the worktree's name (.worktrees/<task>); sbx agent also exports SBX_TASK."""
    if os.environ.get("SBX_TASK"):
        return os.environ["SBX_TASK"]
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    if top.returncode != 0:
        die("not in a git worktree")
    top_dir = top.stdout.rstrip("\n")
    return os.path.basename(top_dir) if "/.worktrees/" in top_dir else "main"


_bus_dirs: dict[tuple[str, str], Path] = {}


def bus_dir() -> Path:
    """<clone>/.git/sbx/<task>.

    Bus state lives in the shared git dir: every worktree of the clone sees it,
    git ignores it, and it survives container restarts (it's on the clone).
    """
    key = (os.getcwd(), os.environ.get("SBX_TASK", ""))
    if key not in _bus_dirs:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if common.returncode != 0:
            die("not in a git worktree")
        _bus_dirs[key] = Path(common.stdout.rstrip("\n")) / "sbx" / task_name()
    return _bus_dirs[key]


# ---- task state (one small file per key under <bus>/state/) -----------------


def state_get(name: str, default: str = "") -> str:
    """A state value; <default> only when it was never set (a set-but-empty value stays empty)."""
    try:
        return (bus_dir() / "state" / name).read_text().rstrip("\n")
    except OSError:
        return default


def state_set(name: str, value: str) -> None:
    state = bus_dir() / "state"
    state.mkdir(parents=True, exist_ok=True)
    tmp = state / f"{name}.tmp"
    tmp.write_text(value + "\n")
    os.replace(tmp, state / name)


def log_event(message: str) -> None:
    """Append a timestamped line to the task's event log (<bus>/log)."""
    bus = bus_dir()
    bus.mkdir(parents=True, exist_ok=True)
    with open(bus / "log", "a") as log:
        log.write(f"{now()} {message}\n")


# ---- path classes, from the config ------------------------------------------
# Patterns ending in '/' are prefixes; the rest are globs ('*' matches across '/').


def matches_any(path: str, key: str) -> bool:
    for value in conf_all(key):
        for pattern in value.split():
            if pattern.endswith("/"):
                if path.startswith(pattern):
                    return True
            elif fnmatch.fnmatchcase(path, pattern):
                return True
    return False


def is_test_path(path: str) -> bool:
    return matches_any(path, "test_paths")


def is_protected(path: str) -> bool:
    return matches_any(path, "protected")


def is_scratch(path: str) -> bool:
    return matches_any(path, "scratch")


def changed_paths(base: str = "") -> list[str]:
    """Paths the gate judges: committed since <base> (if given) plus anything
    dirty or untracked, minus scratch paths (agent notes, reports)."""
    paths = set()
    if base:
        paths.update(split_lines(git("diff", "--name-only", "--no-renames", base, "HEAD", check=False)))
    status = git("status", "--porcelain", "--untracked-files=all", check=False)
    paths.update(line[3:] for line in split_lines(status))
    return [p for p in sorted(paths) if p and not is_scratch(p)]
