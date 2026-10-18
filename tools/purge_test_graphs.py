#!/usr/bin/env python3
"""List, and with --yes delete, the graphs earlier `pytest -m falkordb` runs left on a shared FalkorDB.

    python tools/purge_test_graphs.py          # a dry run: the graphs it would delete, and the memory
    python tools/purge_test_graphs.py --yes    # delete exactly those graphs, by name

Run it from the repo with the venv active. It reads the FALKORDB_* settings like everything else (the
environment, then `.env`), so with a Cloud `.env` it acts on the Cloud instance.

A leaked test graph is one a test saved under its own process id and did not delete, such as
`e4_pipeline__94766__fix-a`. The instance on FalkorDB Cloud has a 100 MB cap and never evicts, so enough of
them make every later `pytest -m falkordb` fail with an out-of-memory error (issue #141). The tests no longer
leak: `tests/conftest.py` fails a module that does, and deletes what it left.

It selects a graph only if its whole name is `<test prefix>__<process id>__<something>`, for one of the
prefixes in `TEST_PREFIXES`. The product's graphs (`demo-infra__*`), the fixtures (`fx__*`), the review
documents (`theseus__docs`) and the benchmark (`theseus__benchmark`) can never match, because none starts with
a test prefix. `delete_graphs` checks every name again before it deletes the first.

Run it when nobody is running `pytest -m falkordb` against the instance: a test run in progress has graphs of
the same shape, and deleting them fails that run. Closed PRs' graphs are `python -m theseus prune`'s, not this
script's.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from theseus.config import get_settings
from theseus.errors import GraphError
from theseus.graph.client import GRAPH_MB, Memory, get_client, memory
from theseus.graph.store import FalkorStore

log = logging.getLogger(__name__)

# One per test that saves graphs under its own process id (tests/integration and tests/golden name them).
TEST_PREFIXES = (
    "a6_mcp",
    "c3_scan",
    "e4_parity",
    "e4_pipeline",
    "fm3_parity",
    "fm4_parity",
    "parity",
    "reviewreads",
    "smoke",
)
# [0-9], not \d, which also matches digits of other scripts; fullmatch, not $, which lets a newline through.
LEAKED = re.compile("(?:" + "|".join(re.escape(p) for p in TEST_PREFIXES) + ")__[0-9]+__.+")


def is_leaked(name: str) -> bool:
    """True when the whole name is `<test prefix>__<process id>__<something>`."""
    return LEAKED.fullmatch(name) is not None


def leaked_graphs(names: Iterable[str]) -> list[str]:
    """The names that are leaked test graphs, sorted. Nothing else is ever in it."""
    return sorted(name for name in names if is_leaked(name))


def delete_graphs(
    db: Any, names: Sequence[str], on_deleted: Callable[[str], None] = lambda name: None
) -> None:
    """Delete each graph in `names` from `db`, calling `on_deleted(name)` after each one.

    Raises ValueError, before it deletes anything, when a name is not a leaked test graph. Raises GraphError
    at the first graph the server will not delete; the ones before it are gone."""
    refused = [name for name in names if not is_leaked(name)]
    if refused:
        raise ValueError(f"not a leaked test graph, nothing deleted: {', '.join(refused)}")
    store = FalkorStore(db)
    for name in names:
        store.delete(name)
        on_deleted(name)


def read_memory(db: Any) -> Memory | None:
    """The server's memory, or None (with a warning) when it will not say: purging does not need it."""
    try:
        return memory(db)
    except GraphError as e:
        log.warning("%s", e)
        return None


def memory_line(reading: Memory | None) -> str:
    if reading is None:
        return "the server's memory is not available."
    limit = f" of {reading.limit_mb:.1f} MB" if reading.limit_mb else ""
    return f"{reading.used_mb:.1f} MB used{limit}."


def count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def describe(where: str, names: Sequence[str], reading: Memory | None) -> str:
    """What the script found, to read before running it with --yes: the instance, its memory, each leaked
    graph by name, and what they cost."""
    lines = [f"FalkorDB at {where}: {memory_line(reading)}", ""]
    if not names:
        lines.append("Nothing to delete: no leaked test graph is on the instance.")
        return "\n".join(lines)
    lines.append("Leaked test graphs (<test>__<process id>__<name>):")
    lines.extend(f"  {name}" for name in names)
    lines.append(
        f"That is {count(len(names), 'graph')}, about {len(names) * GRAPH_MB:.1f} MB "
        "(an estimate: a graph's own size cannot be read)."
    )
    lines.append("A test run in progress has graphs like these: run this when nobody is running the tests.")
    return "\n".join(lines)


def purge(db: Any, where: str, yes: bool) -> int:
    """List the leaked test graphs on `db`, and with `yes` delete exactly those, printing the memory before
    and after. Returns 0, or 1 when the server will not list or delete."""
    try:
        names = leaked_graphs(FalkorStore(db).list_graphs())
        before = read_memory(db)
        print(describe(where, names, before))
        if not names:
            return 0
        print()
        if not yes:
            print("Dry run: nothing was deleted. Run it again with --yes to delete the graphs listed above.")
            return 0
        gone: list[str] = []

        def report(name: str) -> None:
            gone.append(name)
            print(f"deleted {name}")

        try:
            delete_graphs(db, names, report)
        except GraphError as e:
            print(
                f"purge_test_graphs: {e}; deleted {len(gone)} of {len(names)} before it, and left the rest.",
                file=sys.stderr,
            )
            return 1
        after = read_memory(db)
    except GraphError as e:
        print(f"purge_test_graphs: {e}", file=sys.stderr)
        return 1
    print(f"Deleted {count(len(names), 'graph')}.")
    if before is not None and after is not None:
        limit = f" ({after.limit_mb:.1f} MB limit)" if after.limit_mb else ""
        print(f"Memory: {before.used_mb:.1f} MB before, {after.used_mb:.1f} MB after{limit}.")
    else:
        print("Memory: the server's memory is not available, so there is no before and after.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; returns the exit status."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--yes",
        action="store_true",
        help="delete the graphs listed; without it nothing is deleted",
    )
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        db = get_client(settings)
    except GraphError as e:
        print(f"purge_test_graphs: {e}", file=sys.stderr)
        return 1
    return purge(db, f"{settings.falkordb_host}:{settings.falkordb_port}", args.yes)


if __name__ == "__main__":
    sys.exit(main())
