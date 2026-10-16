"""Register the Theseus GitHub App from deploy/github-app-manifest.json (deploy/README.md, "The GitHub App").

    python tools/github_app.py form --domain theseus.example.com   # writes a page; open it, click Create
    python tools/github_app.py convert <code> --out <dir>          # within an hour: saves key and secrets

`form` fills the webhook URL with the domain and writes a page that posts the manifest to GitHub. After you
create the App, GitHub sends you to the repo page with `?code=...` in the address bar. `convert` trades that
code for the App's ID, private key and webhook secret, and writes them to files readable only by you: it never
prints a secret.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "deploy" / "github-app-manifest.json"
NEW_APP = "https://github.com/settings/apps/new"
CONVERT = "https://api.github.com/app-manifests/{code}/conversions"


def manifest(domain: str) -> dict:
    """The manifest with the webhook URL pointing at the domain."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    data["hook_attributes"]["url"] = data["hook_attributes"]["url"].replace("<DOMAIN>", domain)
    return data


def form(domain: str) -> Path:
    """An HTML page whose button posts the manifest to GitHub's new-App page. Returns its path."""
    value = html.escape(json.dumps(manifest(domain)), quote=True)
    page = (
        "<!doctype html><meta charset='utf-8'><title>Register Theseus</title>"
        f"<form action='{NEW_APP}' method='post'>"
        f"<input type='hidden' name='manifest' value='{value}'>"
        "<p>GitHub shows the App's settings next; check them, then click Create GitHub App.</p>"
        "<button type='submit'>Register the Theseus GitHub App</button></form>"
    )
    path = Path(tempfile.gettempdir()) / "theseus-register-app.html"
    path.write_text(page, encoding="utf-8")
    return path


def _private(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)


def convert(code: str, out: Path) -> dict:
    """Trades the code for the App's credentials and writes them under `out`. Returns what is safe to show."""
    request = urllib.request.Request(
        CONVERT.format(code=code),
        method="POST",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "theseus"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        app = json.load(response)
    out.mkdir(parents=True, exist_ok=True)
    _private(out / "theseus.private-key.pem", app["pem"])
    _private(
        out / "github-app.env",
        f"GITHUB_APP_ID={app['id']}\n"
        "GITHUB_APP_PRIVATE_KEY_PATH=/app/secrets/theseus.private-key.pem\n"
        f"GITHUB_WEBHOOK_SECRET={app['webhook_secret']}\n",
    )
    return {"id": app["id"], "slug": app["slug"], "html_url": app["html_url"], "saved_to": str(out)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("form", help="write the registration page")
    f.add_argument("--domain", required=True, help="the API's public hostname, as in DOMAIN")
    c = sub.add_parser("convert", help="save the App's key and secrets from the redirect's code")
    c.add_argument("code")
    c.add_argument("--out", type=Path, required=True, help="a folder outside the repo")
    args = parser.parse_args()
    if args.command == "form":
        print(f"Open this file in a browser and click the button: {form(args.domain)}")
        return 0
    if (ROOT in args.out.resolve().parents) or args.out.resolve() == ROOT:
        print("--out must be outside the repo, so the key is never committed", file=sys.stderr)
        return 2
    print(json.dumps(convert(args.code, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
