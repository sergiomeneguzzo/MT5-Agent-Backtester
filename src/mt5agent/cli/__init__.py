from __future__ import annotations

import argparse
import sys

from .._version import __version__
from ..errors import MT5Error
from .commands import COMMANDS, Context
from .output import Output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mt5agent", description="Drive the MetaTrader 5 Strategy Tester from code.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--no-color", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in COMMANDS.values():
        p = sub.add_parser(cmd.name, help=cmd.help)
        for flags, options in cmd.arguments:
            p.add_argument(*flags, **options)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = Output(as_json=args.json, color=False if args.no_color else None)
    try:
        COMMANDS[args.command].handler(Context(args, out))
    except (MT5Error, RuntimeError, ValueError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = ["build_parser", "main"]
