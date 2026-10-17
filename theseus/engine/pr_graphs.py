"""Which graphs belong to a pull request, which of them it keeps while it is open, and which it leaves behind
once it is closed (03-graph.md, "One graph per state").

A review loads `<world>__pr<N>-base` and `-head`, then one `-fix-<id>` copy of the head for each candidate it
lists (`graph_name` in `engine/pipeline.py`, `candidate_graph` in `engine/simulate.py`). The names do not say
which repo the PR is in, so a PR number stands for the same graphs in every repo that shares a world root.

Everything here reasons on names, or on the `GraphStore` it is given: no network and no environment.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from theseus.contracts.engine import GraphStore
from theseus.graph.load import delete_graph

log = logging.getLogger(__name__)

# What follows `<world>__` in a PR's graph name: `pr7-base`, `pr7-head`, `pr7-fix-b`, `pr7-fix-h1`.
PR_GRAPH: Final = re.compile(r"^pr(?P<number>\d+)-(?P<part>base|head|fix-[a-z0-9]+)$")
PR_HEAD: Final = re.compile(r"__pr\d+-head$")
# A graph that is no PR's whatever it is called: `main`, the fixtures', the documents and the benchmark.
PROTECTED_PREFIXES: Final = ("fx__", "theseus__")
PROTECTED_SUFFIXES: Final = ("__main",)
# What GitHub calls a PR that is done with.
DONE: Final = frozenset({"closed", "merged"})


def world_name(world_root: str) -> str:
    """The `<world>` of the graph names for a world root such as `demo-infra`: its last folder, lowercased,
    with anything outside the store's grammar (`a-z`, `0-9`, `-`, `_`) made a `-`, as `graph_name` does."""
    return re.sub(r"[^a-z0-9_-]", "-", Path(world_root.strip("/")).name.lower())


def parse(name: str, world: str) -> tuple[int, str] | None:
    """`(number, part)` for a graph a review of a PR in this world makes, such as `(7, "fix-b")`; None for
    every other graph, and for any that is protected."""
    if name.startswith(PROTECTED_PREFIXES) or name.endswith(PROTECTED_SUFFIXES):
        return None
    prefix = f"{world}__"
    if not name.startswith(prefix):
        return None
    found = PR_GRAPH.fullmatch(name.removeprefix(prefix))
    return (int(found["number"]), found["part"]) if found else None


def pr_graphs(names: Iterable[str], world: str, number: int) -> list[str]:
    """The names, sorted, of PR `number`'s graphs among `names`: its base, its head and every fix."""
    return sorted(n for n in names if (parsed := parse(n, world)) is not None and parsed[0] == number)


def delete_pr_graphs(store: GraphStore, world: str, number: int) -> list[str]:
    """Deletes PR `number`'s graphs and returns their names, sorted. Its review, kept apart in the documents
    graph, stays; a PR with no graphs is a no-op."""
    removed = pr_graphs(store.list_graphs(), world, number)
    for name in removed:
        delete_graph(store, name)
    return removed


def _is_pr_head(name: str) -> bool:
    """Whether `name` is a PR's head graph (`<world>__pr7-head`) and not a protected graph's."""
    return PR_HEAD.search(name) is not None and not name.startswith(PROTECTED_PREFIXES)


def stale_fixes(names: Iterable[str], head: str, keep: Iterable[str]) -> list[str]:
    """The fix graphs of the PR `head` belongs to that no candidate in `keep` (their IDs, such as `A`) names,
    sorted. Only a PR's head has any: anything else, a fixture's included, gives none."""
    if not _is_pr_head(head):
        return []
    prefix = head.removesuffix("-head") + "-fix-"
    wanted = {prefix + candidate.lower() for candidate in keep}
    return sorted(n for n in names if n.startswith(prefix) and n not in wanted)


def drop_stale_fixes(store: GraphStore, head: str, keep: Iterable[str]) -> list[str]:
    """Deletes the fix graphs an earlier review of the PR left that the newest review no longer lists, and
    returns their names. A review that lists the same candidates replaces its graphs under the same names,
    so a PR holds its base, its head and one fix graph for each candidate of its newest review."""
    if not _is_pr_head(head):
        return []
    stale = stale_fixes(store.list_graphs(), head, keep)
    for name in stale:
        delete_graph(store, name)
    return stale


# What `python -m theseus prune` does ----------------------------------------------------------------------


class PrGroup(BaseModel):
    """One PR's graphs in a prune plan, with the state GitHub gave it: `open`, `closed`, `merged` or
    `unknown` (GitHub does not list it)."""

    model_config = ConfigDict(frozen=True)

    number: int
    state: str
    graphs: tuple[str, ...]


class PrunePlan(BaseModel):
    """The graphs of PRs that are done (`delete`) and of those that are not or are not known (`keep`), each
    sorted by PR number."""

    model_config = ConfigDict(frozen=True)

    delete: tuple[PrGroup, ...]
    keep: tuple[PrGroup, ...]

    @property
    def names(self) -> list[str]:
        """Every graph to delete, grouped by PR and sorted within it: the only names `prune --yes` deletes."""
        return [name for group in self.delete for name in group.graphs]


def plan_prune(names: Iterable[str], world: str, states: Mapping[int, str]) -> PrunePlan:
    """What to delete from `names`: the graphs of the PRs `states` calls closed or merged, and only theirs. A
    graph that is not a PR's in this world is not mentioned; a PR open or missing from `states` is kept."""
    by_number: dict[int, list[str]] = {}
    for name in names:
        parsed = parse(name, world)
        if parsed is not None:
            by_number.setdefault(parsed[0], []).append(name)
    delete, keep = [], []
    for number in sorted(by_number):
        state = states.get(number, "unknown")
        group = PrGroup(number=number, state=state, graphs=tuple(sorted(by_number[number])))
        (delete if state in DONE else keep).append(group)
    return PrunePlan(delete=tuple(delete), keep=tuple(keep))


def merge_states(per_repo: Iterable[Mapping[int, str]]) -> dict[int, str]:
    """One state for each PR number across repos: `open` if any repo has it open (its graphs may be that
    repo's), else `closed` if any has it closed, else `merged`. Graph names do not name the repo."""
    rank = {"open": 0, "closed": 1, "merged": 2}
    merged: dict[int, str] = {}
    for states in per_repo:
        for number, state in states.items():
            if number not in merged or rank[state] < rank[merged[number]]:
                merged[number] = state
    return merged
