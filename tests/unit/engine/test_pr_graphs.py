"""Which graphs belong to a PR, which of them it keeps while it is open, and which a closed PR leaves behind
(03-graph.md, "One graph per state"). Everything here is pure or runs on MemoryStore: no network."""

from __future__ import annotations

import pytest

from theseus.contracts.result import GraphRows, NodeRow
from theseus.engine import pr_graphs
from theseus.engine.pr_graphs import PrGroup, plan_prune
from theseus.graph.store import MemoryStore

WORLD = "demo-infra"
# What a busy instance holds: main, a finding, PRs whose numbers share digits, fixtures, the documents, the
# benchmark, another world's PR and a leaked test graph.
NAMES = [
    "demo-infra__main",
    "demo-infra__finding-ghsa-demo-0001",
    "demo-infra__pr1-base",
    "demo-infra__pr1-head",
    "demo-infra__pr1-fix-a",
    "demo-infra__pr12-base",
    "demo-infra__pr12-head",
    "demo-infra__pr12-fix-b",
    "demo-infra__pr7-base",
    "demo-infra__pr7-head",
    "demo-infra__pr7-fix-a",
    "demo-infra__pr7-fix-c",
    "demo-infra__pr70-head",
    "demo-infra__pr70-fix-a",
    "fx__intern__base",
    "fx__intern__head",
    "fx__intern__fix-a",
    "theseus__docs",
    "theseus__benchmark",
    "other-world__pr7-head",
    "e4_pipeline__94766__fix-a",
]


def test_a_prs_graphs_are_its_base_its_head_and_every_fix_and_no_others() -> None:
    assert pr_graphs.pr_graphs(NAMES, WORLD, 7) == [
        "demo-infra__pr7-base",
        "demo-infra__pr7-fix-a",
        "demo-infra__pr7-fix-c",
        "demo-infra__pr7-head",
    ]


def test_pr_1_does_not_take_pr_12_or_pr_70_with_it() -> None:
    assert pr_graphs.pr_graphs(NAMES, WORLD, 1) == [
        "demo-infra__pr1-base",
        "demo-infra__pr1-fix-a",
        "demo-infra__pr1-head",
    ]
    assert pr_graphs.pr_graphs(NAMES, WORLD, 70) == ["demo-infra__pr70-fix-a", "demo-infra__pr70-head"]


@pytest.mark.parametrize("number", [0, 2, 8, 120, 999])
def test_a_pr_with_no_graphs_has_none(number: int) -> None:
    assert pr_graphs.pr_graphs(NAMES, WORLD, number) == []


@pytest.mark.parametrize(
    ("name", "parsed"),
    [
        ("demo-infra__pr7-base", (7, "base")),
        ("demo-infra__pr7-head", (7, "head")),
        ("demo-infra__pr85-fix-b", (85, "fix-b")),
        ("demo-infra__pr3-fix-h1", (3, "fix-h1")),
        ("demo-infra__main", None),
        ("demo-infra__pr7", None),
        ("demo-infra__pr7-", None),
        ("demo-infra__pr7-fix-", None),
        ("demo-infra__pr7-other", None),
        ("demo-infra__prx-head", None),
        ("demo-infra__pr7-head-extra", None),
        ("demo-infra__pr7-head__pr8-head", None),
        ("demo-infra__finding-ghsa-demo-0001", None),
        ("other-world__pr7-head", None),
        ("fx__intern__head", None),
        ("parity__21806__code-pr-head", None),
    ],
)
def test_only_the_names_the_pipeline_makes_for_a_pr_parse(name: str, parsed: tuple[int, str] | None) -> None:
    assert pr_graphs.parse(name, WORLD) == parsed


@pytest.mark.parametrize(
    ("world_root", "world"),
    [
        ("demo-infra", "demo-infra"),
        ("demo-infra/", "demo-infra"),
        ("infra/AWS", "aws"),
        ("My World", "my-world"),
    ],
)
def test_the_world_is_named_as_the_pipeline_names_it(world_root: str, world: str) -> None:
    assert pr_graphs.world_name(world_root) == world


# The plan for `prune` -------------------------------------------------------------------------------------


def group(number: int, state: str, *names: str) -> PrGroup:
    return PrGroup(number=number, state=state, graphs=tuple(names))


def test_a_closed_or_merged_prs_graphs_are_listed_to_delete_and_the_rest_are_kept() -> None:
    plan = plan_prune(NAMES, WORLD, {1: "closed", 7: "merged", 12: "open"})
    assert plan.delete == (
        group(1, "closed", "demo-infra__pr1-base", "demo-infra__pr1-fix-a", "demo-infra__pr1-head"),
        group(
            7,
            "merged",
            "demo-infra__pr7-base",
            "demo-infra__pr7-fix-a",
            "demo-infra__pr7-fix-c",
            "demo-infra__pr7-head",
        ),
    )
    assert plan.keep == (
        group(12, "open", "demo-infra__pr12-base", "demo-infra__pr12-fix-b", "demo-infra__pr12-head"),
        group(70, "unknown", "demo-infra__pr70-fix-a", "demo-infra__pr70-head"),
    )
    assert plan.names == [name for g in plan.delete for name in g.graphs]


def test_a_pr_github_does_not_list_is_left_alone() -> None:
    plan = plan_prune(NAMES, WORLD, {})
    assert plan.delete == () and plan.names == []
    assert {g.state for g in plan.keep} == {"unknown"}


def test_prune_never_selects_main_fixtures_documents_the_benchmark_or_an_open_prs_graphs() -> None:
    everything_closed = dict.fromkeys(range(0, 200), "closed")
    plan = plan_prune(NAMES, WORLD, everything_closed)
    protected = {
        "demo-infra__main",
        "demo-infra__finding-ghsa-demo-0001",
        "fx__intern__base",
        "fx__intern__head",
        "fx__intern__fix-a",
        "theseus__docs",
        "theseus__benchmark",
        "other-world__pr7-head",
        "e4_pipeline__94766__fix-a",
    }
    assert protected.isdisjoint(plan.names)
    # Nor does it mention them: they are not PR graphs of this world at all.
    assert protected.isdisjoint(name for g in plan.keep for name in g.graphs)
    opened = plan_prune(NAMES, WORLD, {**everything_closed, 7: "open"})
    assert not [n for n in opened.names if n.startswith("demo-infra__pr7-")]
    assert [g.number for g in opened.keep] == [7]


@pytest.mark.parametrize("world", ["fx", "theseus"])
def test_a_world_called_like_a_protected_prefix_is_still_never_pruned(world: str) -> None:
    names = [f"{world}__pr3-head", f"{world}__pr3-base", f"{world}__main"]
    plan = plan_prune(names, world, {3: "closed"})
    assert plan.names == [] and plan.delete == ()


def test_a_main_graph_that_looks_like_a_pr_graph_is_still_protected() -> None:
    plan = plan_prune(["demo-infra__pr3-main", "demo-infra__main"], WORLD, {3: "closed"})
    assert plan.names == []


def test_the_plan_is_sorted_and_does_not_depend_on_the_order_of_the_names() -> None:
    states = {1: "closed", 7: "closed", 12: "closed"}
    assert plan_prune(NAMES, WORLD, states) == plan_prune(list(reversed(NAMES)), WORLD, states)
    assert [g.number for g in plan_prune(NAMES, WORLD, states).delete] == [1, 7, 12]


def test_a_pr_open_in_any_repo_keeps_its_graphs_because_graph_names_do_not_name_the_repo() -> None:
    assert pr_graphs.merge_states([{7: "closed", 8: "closed"}, {7: "open"}]) == {7: "open", 8: "closed"}
    assert pr_graphs.merge_states([{7: "merged"}, {7: "closed"}]) == {7: "closed"}
    assert pr_graphs.merge_states([{7: "merged"}]) == {7: "merged"}
    assert pr_graphs.merge_states([]) == {}


# Keeping and dropping graphs in a store -------------------------------------------------------------------


def rows(*ids: str) -> GraphRows:
    return GraphRows(nodes=[NodeRow(id=i, labels=["Node"], name=i) for i in ids])


def store_with(*names: str) -> MemoryStore:
    store = MemoryStore()
    for name in names:
        store.load(name, rows("a"))
    return store


def test_closing_a_pr_deletes_only_its_graphs_and_says_which() -> None:
    loaded = [n for n in NAMES if n != "theseus__docs"]
    store = store_with(*loaded)
    store.put_doc("review:acme/infra#7", "{}")
    removed = pr_graphs.delete_pr_graphs(store, WORLD, 7)
    assert removed == [
        "demo-infra__pr7-base",
        "demo-infra__pr7-fix-a",
        "demo-infra__pr7-fix-c",
        "demo-infra__pr7-head",
    ]
    assert not [n for n in store.list_graphs() if n.startswith("demo-infra__pr7-")]
    assert store.list_graphs() == sorted(set(loaded) - set(removed))
    assert store.get_doc("review:acme/infra#7") == "{}"
    assert pr_graphs.delete_pr_graphs(store, WORLD, 7) == []  # closing twice is harmless


def test_a_review_keeps_a_fix_graph_only_for_the_candidates_it_lists() -> None:
    head = "demo-infra__pr7-head"
    names = [head, "demo-infra__pr7-fix-a", "demo-infra__pr7-fix-c", "demo-infra__pr7-fix-d"]
    assert pr_graphs.stale_fixes([*names, "demo-infra__pr70-fix-a"], "demo-infra__pr7-head", ["A", "D"]) == [
        "demo-infra__pr7-fix-c"
    ]
    assert pr_graphs.stale_fixes(names, "demo-infra__pr7-head", ["A", "C", "D"]) == []
    assert pr_graphs.stale_fixes(names, "demo-infra__pr7-head", []) == [
        "demo-infra__pr7-fix-a",
        "demo-infra__pr7-fix-c",
        "demo-infra__pr7-fix-d",
    ]


@pytest.mark.parametrize(
    "head",
    ["fx__intern__head", "demo-infra__main", "demo-infra__pr7-base", "fx__pr7-head", "theseus__pr7-head", ""],
)
def test_only_a_pr_head_has_stale_fixes(head: str) -> None:
    assert pr_graphs.stale_fixes(["fx__intern__fix-a", "demo-infra__pr7-fix-a"], head, []) == []


def test_dropping_stale_fixes_deletes_them_and_nothing_else() -> None:
    store = store_with(
        "demo-infra__pr7-base",
        "demo-infra__pr7-head",
        "demo-infra__pr7-fix-a",
        "demo-infra__pr7-fix-c",
        "demo-infra__pr70-fix-a",
    )
    assert pr_graphs.drop_stale_fixes(store, "demo-infra__pr7-head", ["A"]) == ["demo-infra__pr7-fix-c"]
    assert store.list_graphs() == [
        "demo-infra__pr7-base",
        "demo-infra__pr7-fix-a",
        "demo-infra__pr7-head",
        "demo-infra__pr70-fix-a",
    ]


def test_a_world_whose_name_holds_a_double_underscore_still_finds_its_prs() -> None:
    assert pr_graphs.parse("my__world__pr7-head", "my__world") == (7, "head")
    assert pr_graphs.parse("my__world__pr7-head", "my") is None
