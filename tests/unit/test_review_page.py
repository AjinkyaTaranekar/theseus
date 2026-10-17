"""The review page (theseus/web/review.html) and the dashboard (dashboard.html) load: their scripts
parse. A syntax error there shows a blank page with no test failing anywhere else, so Node checks it wherever
Node is installed (GitHub's runners have it)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PAGES = [Path("theseus/web/review.html"), Path("theseus/web/dashboard.html")]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node to parse the page's script")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_the_page_script_parses(page: Path, tmp_path: Path) -> None:
    html = page.read_text(encoding="utf-8")
    script = tmp_path / "page.js"
    script.write_text(html.split("<script>", 1)[1].split("</script>", 1)[0], encoding="utf-8")
    # From a file, not stdin: a Windows runner's pipe once held Node past the timeout.
    check = "new Function(require('fs').readFileSync(process.argv[1], 'utf8'))"
    run = subprocess.run(
        ["node", "-e", check, str(script)], capture_output=True, text=True, encoding="utf-8", timeout=90
    )
    assert run.returncode == 0, run.stderr


def _review() -> str:
    return Path("theseus/web/review.html").read_text(encoding="utf-8")


def test_the_page_shows_a_skeleton_until_its_data_arrives() -> None:
    """A slow `/data` must not look like a blank page: the skeleton shows from first paint, `render` and
    `fail` both take it down, and a reply that never comes ends in a message with a way to try again."""
    html = _review()
    assert 'id="loading"' in html
    assert html.count('$("loading").hidden = true') >= 2
    assert "AbortController" in html and "Try again" in html
    assert "prefers-reduced-motion" in html


def test_the_fix_graphs_load_before_anyone_clicks() -> None:
    """Each passing fix's graph is fetched once, in the background, so its tab opens at once."""
    html = _review()
    assert "function loadFix(" in html and "function prefetchFixes(" in html
    assert html.count('fetch(`${location.pathname.replace(/\\/$/, "")}/fixes/') == 1


def test_a_pr_review_says_what_to_do() -> None:
    """The What to do section is filled for a PR with a passing fix, from the candidate's own fields, and is
    no longer reached only through the finding branch."""
    html = _review()
    script = html.split("<script>", 1)[1]
    assert "function fixCards(" in script and "function opLine(" in script
    assert 'fixCards($("todo"))' in script
    for field in ("paths_left", "requirements_broken", "calls_broken", "recommended"):
        assert field in script.split("function fixCards(", 1)[1].split("\n}\n", 1)[0]
    assert "/theseus apply" in script


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_the_page_writes_no_data_as_html(page: Path) -> None:
    """Everything from a review reaches the page through textContent or attributes, never innerHTML."""
    html = page.read_text(encoding="utf-8")
    assert "innerHTML" not in html and "insertAdjacentHTML" not in html and "document.write" not in html


def test_a_review_whose_graphs_were_removed_says_so_in_words_and_offers_no_graph_view() -> None:
    """A closed PR's graphs are deleted but its review is kept. The page says that, in a notice of its own,
    instead of drawing an empty graph, and neither the whole-graph view nor a fix's view is offered."""
    html = _review()
    notice = html.split('id="removed"', 1)[1].split("</p>", 1)[0]
    assert "hidden" in html.split('id="removed"', 1)[1][:80]
    assert "no longer in FalkorDB" in notice and "when it closes" in notice and "reopen" in notice.lower()
    script = html.split("<script>", 1)[1]
    assert "data.graphs_removed" in script
    assert '$("removed").hidden = !gone' in script
    assert '$("v-full").disabled = gone' in script and "b.disabled = gone" in script
    assert "if (fixes.length && !gone) setTimeout(prefetchFixes, 0)" in script
    # The two places that used to say only "isn't in the store any more" now say why.
    assert "isn't in the store any more" not in script
    assert script.count("removed when a PR closes") >= 2
