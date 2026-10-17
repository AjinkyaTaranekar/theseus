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


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_the_page_writes_no_data_as_html(page: Path) -> None:
    """Everything from a review reaches the page through textContent or attributes, never innerHTML."""
    html = page.read_text(encoding="utf-8")
    assert "innerHTML" not in html and "insertAdjacentHTML" not in html and "document.write" not in html
