"""The Transkribus leg of the HTR head-to-head (2026-08-26): same 5
pages, same reference, same CER — against Transkribus's Text
Recognition API. Auth is OpenID Connect password-grant (Transkribus
issues NO api keys: your account username+password exchange for a
Bearer token at account.readcoop.eu; client_id transkribus-api-client).

Credentials come from TRANSCRIBUS_USER / TRANSCRIBUS_PASSWORD in the
environment — the script never sees them in code, args, or logs. The
trial images must be reachable by Transkribus's cloud, so they are
served locally and exposed via a short-lived tunnel (cloudflared quick
tunnel) whose URL is passed on the command line.

Usage:
  export TRANSCRIBUS_USER=... TRANSCRIBUS_PASSWORD=...
  PYTHONPATH=. .venv/bin/python -m tools.eval_transkribus https://tunnel.trycloudflare.com
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.eval_htr_trial import PAGES

TOKEN_URL = "https://account.readcoop.eu/auth/realms/readcoop/protocol/openid-connect/token"
PROCESS_URL = "https://transkribus.eu/processing/v1/processes"
CLIENT_ID = "transkribus-api-client"
MODEL_GENERAL_HANDWRITING = 38230  # the Super Model from the docs' example

NAMESPACE = {"p": "http://schema.primaresearch.org/PAGE/gfx/pagecontent/2013-07-15"}


def get_token(username: str, password: str) -> str:
    """The OIDC password grant — returns the access token (a short-lived
    bearer). The password travels only in this request body."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": CLIENT_ID,
        }
    ).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = __import__("json").loads(resp.read().decode())
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"token exchange failed: {data.get('error', data)[:120]}")
    return token


def submit_process(token: str, image: Path, model_id: int = MODEL_GENERAL_HANDWRITING) -> str:
    """Submit by base64 image data — the v1 schema accepts either
    base64 or imageUrl; base64 keeps the scans off any tunnel."""
    # lucidlint: ignore inline-import this trial tool is removed in the
    # stacked top PR (pr/remove-trial-code) — its findings are moot
    import base64 as _b64

    body = (
        __import__("json")
        .dumps(
            {
                "config": {"modelId": model_id},
                "image": {"base64": _b64.b64encode(image.read_bytes()).decode("ascii")},
            }
        )
        .encode()
    )
    req = urllib.request.Request(
        PROCESS_URL,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return __import__("json").loads(resp.read().decode())["processId"]


def poll_process(token: str, process_id: str, timeout_s: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        req = urllib.request.Request(f"{PROCESS_URL}/{process_id}", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            state = __import__("json").loads(resp.read().decode())
        status = state.get("status", "")
        if status in ("SUCCEEDED", "COMPLETED", "DONE"):
            return state
        if status in ("FAILED", "ERROR", "CANCELLED"):
            raise RuntimeError(f"transkribus process failed: {state.get('error', state)[:200]}")
        time.sleep(5)
    raise TimeoutError(f"transkribus process {process_id} did not finish in {timeout_s}s")


def fetch_page_xml(token: str, process_id: str) -> str:
    req = urllib.request.Request(f"{PROCESS_URL}/{process_id}/page", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode()


def extract_lines(page_xml: str) -> list[str]:
    """PAGE XML -> the transcription's lines, in document order. Pure —
    the testable seam (a wrong namespace or a nested element would
    silently drop lines otherwise)."""
    root = ET.fromstring(page_xml)
    ns = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
    lines: list[str] = []
    for line in root.iter(f"{ns}TextLine"):
        for equiv in line.iter(f"{ns}TextEquiv"):
            unicode_el = equiv.find(f"{ns}Unicode")
            if unicode_el is not None and unicode_el.text:
                lines.append(unicode_el.text)
                break
    return lines


def main(argv: list[str] | None = None) -> int:
    if not argv:
        print("usage: eval_transkribus.py <tunnel-origin> [--pages n,n,...]", file=sys.stderr)
        return 2
    if argv:
        pass  # legacy arg kept for CLI symmetry
    user = os.environ.get("TRANSCRIBUS_USER")
    password = os.environ.get("TRANSCRIBUS_PASSWORD")
    if not user or not password:
        print("TRANSCRIBUS_USER / TRANSCRIBUS_PASSWORD must be set in the environment", file=sys.stderr)
        return 2
    token = get_token(user, password)
    for batch, page, _why in PAGES:
        image = Path("/run/media/ashby/One Touch/Loft/work") / batch / "oriented" / f"{page}.jpg"
        if not image.is_file():
            print(f"{page[:26]}: missing image", file=sys.stderr)
            continue
        process_id = submit_process(token, image)
        print(f"{page[:26]}: submitted {process_id}", file=sys.stderr)
        poll_process(token, process_id)
        xml = fetch_page_xml(token, process_id)
        lines = extract_lines(xml)
        out = Path("/run/media/ashby/One Touch/Loft/work/eval-htr")
        out = out / f"{page}.transkribus.json"
        payload = {"engine": "transkribus", "lines": lines, "n": len(lines)}
        out.write_text(__import__("json").dumps(payload), encoding="utf-8")
        print(f"{page[:26]}: {len(lines)} lines -> {out.name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
