"""The review page (theseus/web/review.html) loads: its script parses. A syntax error there shows a blank
page with no test failing anywhere else, so Node checks it wherever Node is installed (GitHub's runners have
it)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path("theseus/web/review.html")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node to parse the page's script")
def test_the_review_page_script_parses() -> None:
    html = PAGE.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    check = "new Function(require('fs').readFileSync(0, 'utf8'))"
    run = subprocess.run(["node", "-e", check], input=script, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr


def test_the_review_page_writes_no_data_as_html() -> None:
    """Everything from a review reaches the page through textContent or attributes, never innerHTML."""
    html = PAGE.read_text(encoding="utf-8")
    assert "innerHTML" not in html and "insertAdjacentHTML" not in html and "document.write" not in html
