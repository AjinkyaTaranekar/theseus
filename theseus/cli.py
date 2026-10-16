"""Command line: `python -m theseus analyze | finding | scan | serve`.

`serve` runs the API (F3). The others print "not implemented yet" and exit 2 until the task that builds them
lands (analyze: E3, finding: FM3, scan: C3). A composition root (docs/spec/08-core-and-adapters.md).
"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from theseus import __version__
from theseus.config import get_settings
from theseus.errors import GraphError
from theseus.graph.client import get_client


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
    commands.add_parser("serve", help="run the API on http://localhost:8000; needs FalkorDB")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return serve()
    print(f"theseus {args.command}: not implemented yet", file=sys.stderr)
    return 2


def serve() -> int:
    """Run the API on localhost:8000, or exit 1 when FalkorDB cannot be reached (rule 3)."""
    try:
        get_client(get_settings())
    except GraphError as e:
        print(f"theseus serve: {e}", file=sys.stderr)
        return 1
    # Theseus's own messages, and each GitHub call httpx makes; uvicorn configures only its own loggers.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("theseus.api.app:app", host="127.0.0.1", port=8000)
    return 0


def run() -> None:
    """Console entry point."""
    sys.exit(main())
