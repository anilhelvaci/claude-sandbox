"""A tiny subcommand dispatcher shared by sbx, bus, gate and proxy.

Why not argparse: several commands pass the rest of their arguments through
untouched (`sbx build <docker args>`, `sbx agent ... <claude args>`,
`sbx bus ... <bus args>`, message text for `bus send`), and argparse would try
to interpret those. Here every handler receives its raw argument list and
parses it exactly as the original shell scripts did.

What this module adds is help:

    <prog>                       overview (every command, one line each)
    <prog> help                  same
    <prog> help <command>        the full help for one command
    <prog> <command> --help      same (also -h; only as the first argument)
"""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Sequence
from typing import Callable, Optional

Handler = Callable[[list[str]], Optional[int]]


class Command:
    def __init__(self, name: str, args: str, summary: str, details: str, handler: Handler):
        self.name = name  # e.g. "send"
        self.args = args  # e.g. "<to> [-k kind] [text | -]"
        self.summary = summary  # one line for the overview
        self.details = details  # the full help, shown by 'help <name>'
        self.handler = handler  # takes the raw argument list, returns an exit code


class CLI:
    def __init__(
        self,
        prog: str,
        intro: str,
        commands: Sequence[Command],
        footer: str = "",
        default: str = "overview",
        unknown: str = "overview",
    ):
        """
        default: what a bare '<prog>' does: "overview" (print it, exit 0) or
                 "overview-2" (print it, exit 2: the original bus/gate/proxy behavior).
        unknown: what an unknown command does: "overview" (print it, exit 2) or
                 "die" (one-line error, exit 1: the original sbx behavior).
        """
        self.prog = prog
        self.intro = intro.strip("\n")
        self.commands = {c.name: c for c in commands}
        self.footer = footer.strip("\n")
        self.default = default
        self.unknown = unknown

    # ---- help text -------------------------------------------------------

    def overview(self) -> str:
        lines = [f"usage: {self.prog} <command> [args]", "", self.intro, "", "Commands:"]
        for c in self.commands.values():
            left = f"  {c.name} {c.args}".rstrip()
            if len(left) <= 30:
                lines.append(f"{left:<32}{c.summary}")
            else:
                lines.append(left)
                lines.append(" " * 32 + c.summary)
        if self.footer:
            lines += ["", self.footer]
        lines += [
            "",
            f"Run '{self.prog} help <command>' (or '{self.prog} <command> --help') for the details of one command.",
        ]
        return "\n".join(lines)

    def command_help(self, c: Command) -> str:
        usage = f"usage: {self.prog} {c.name} {c.args}".rstrip()
        return f"{usage}\n\n{c.summary}\n\n{textwrap.dedent(c.details).strip()}"

    # ---- dispatch --------------------------------------------------------

    def main(self, argv: list[str]) -> int:
        if not argv:
            print(self.overview())
            return 2 if self.default == "overview-2" else 0
        name, rest = argv[0], argv[1:]
        if name in ("help", "-h", "--help"):
            if rest and rest[0] in self.commands:
                print(self.command_help(self.commands[rest[0]]))
            else:
                print(self.overview())
            return 0
        command = self.commands.get(name)
        if command is None:
            if self.unknown == "die":
                print(f"{self.prog}: unknown command '{name}'; see '{self.prog} help'", file=sys.stderr)
                return 1
            print(self.overview())
            return 2
        if rest and rest[0] in ("-h", "--help"):
            print(self.command_help(command))
            return 0
        return command.handler(rest) or 0

    def run(self) -> None:
        sys.exit(self.main(sys.argv[1:]))
