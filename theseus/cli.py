"""Command line: `python -m theseus analyze | finding | scan | serve`.

Each command prints "not implemented yet" and exits 2 until the task that builds it lands
(analyze: E3, finding: FM3, scan: C3, serve: F3).
"""

from __future__ import annotations

import argparse
import sys

from theseus import __version__


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for every command."""
    parser = argparse.ArgumentParser(prog="theseus", description="Review infrastructure changes as a graph.")
    parser.add_argument("--version", action="version", version=f"theseus {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    for name, text in (
        ("analyze", "analyze a PR fixture: base against head"),
        ("finding", "map the blast radius of an advisory fixture"),
        ("scan", "list dangerous paths and unused grants in main"),
    ):
        commands.add_parser(name, help=text).add_argument("fixture", help="a folder under fixtures/")
    commands.add_parser("serve", help="run the API on http://localhost:8000")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = build_parser().parse_args(argv)
    print(f"theseus {args.command}: not implemented yet", file=sys.stderr)
    return 2


def run() -> None:
    """Console entry point."""
    sys.exit(main())
