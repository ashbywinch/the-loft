"""Scan documents or photos from the Epson FF-680W into the user's scan area.

Capture side of the capture seam (MULTI-DOC-IMPORT-PRD.md R1–R6, TECH-SPEC
§16.13): this module writes <batch-id>-NN.jpg files (300 DPI colour, JPEG
quality 88, the batch id embedded in every file name so a user-renamed
folder stays recoverable) into the user's scan area — tools/loft_paths.py
USER_SCAN_AREA — and writes the batch's registry record (label, source,
page hashes, status pending) into our workspace registry. The folder in the
user's area carries only pages; the label lives in the registry record,
never in the folder name. The FF-680W is added to the user SANE config by
IP because mDNS discovery on the home router is unreliable (2026-08-13).

Usage:
    python tools/scan.py docs --label "Box 1 — Letters 1977"
    python tools/scan.py photos   # prompts for the envelope label
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from PIL import Image

from tools.atomic import atomic_write
from tools.loft_paths import REGISTRY_DIR, USER_SCAN_AREA

INBOX = USER_SCAN_AREA
SANE_CONFIG_DIR = Path.home() / ".config" / "sane"
SCANIMAGE = "scanimage"
RESOLUTION_DPI = 300
JPEG_QUALITY = 88
ADF_SOURCE = "ADF Duplex"  # the FF-680W's single sheet-fed ADF handles letters and photos
MODES = ("docs", "photos")
# per-mode source: one line here if a future device exposes a photo-specific source
SOURCE_BY_MODE: Mapping[str, str] = MappingProxyType({"docs": ADF_SOURCE, "photos": ADF_SOURCE})
SCAN_SOURCE = "epson-ff680w"

_DEVICE_LINE = re.compile(r"^device `([^']+)' is a ")


class ScanError(RuntimeError):
    """A scan run failed; the message is the plain-language line."""


def _sane_env() -> dict[str, str]:
    """SANE_CONFIG_DIR pointing at the user config when it exists.

    The static airscan device entry lives in the user config dir, so
    scanimage must read its config from there, not /etc/sane.d alone.
    """
    env = dict(os.environ)
    if SANE_CONFIG_DIR.is_dir():
        env["SANE_CONFIG_DIR"] = str(SANE_CONFIG_DIR)
    return env


def parse_devices(output: str) -> list[str]:
    """SANE device names from `scanimage -L` output, in report order."""
    return [m.group(1) for m in (_DEVICE_LINE.match(line) for line in output.splitlines()) if m]


def pick_device(devices: list[str]) -> str:
    """Prefer the local USB Epson (epsonds/epkowa), then any EPSON-named airscan, then any airscan."""
    candidates = [d for d in devices if d.startswith(("airscan:", "epsonds:", "epkowa:"))]
    if not candidates:
        detail = ", ".join(devices) if devices else "scanimage -L reported no devices"
        message = f"no scanner found — check the FF-680W is connected (USB or network) ({detail})"
        raise ScanError(message)
    usb = [d for d in candidates if d.startswith(("epsonds:", "epkowa:"))]
    if usb:
        return usb[0]
    for device in candidates:
        if "EPSON" in device.upper():
            return device
    return candidates[0]


def ensure_job_dir(inbox: Path, job: str) -> Path:
    """The job's output directory, created empty; refuses to touch a job that exists."""
    name = job.strip()
    if not re.match(r"^[A-Za-z0-9-]+$", name):
        # the job name becomes the registry's batch id — one charset, the
        # registry's (2026-08-14 final review: a spaced --job registered a
        # batch the registry then rejected)
        raise ScanError(f"job name must be letters, digits, or hyphens — got {job!r}")
    try:
        inbox.mkdir(exist_ok=True)
    except OSError as exc:
        raise ScanError(f"inbox not reachable — is the big disk mounted? ({inbox})") from exc
    job_dir = inbox / name
    if job_dir.exists() and any(job_dir.iterdir()):
        raise ScanError(f"inbox job {name!r} already has files — refusing to overwrite (the inbox is append-only)")
    return job_dir


# inbox/resolution are environment defaults, _scanimage/_env are test seams
# lucidlint: ignore long-param-list a single production call site — device/mode/job are the job's identity,
def scan_job(
    device: str,
    mode: str,
    job: str,
    *,
    inbox: Path = INBOX,
    resolution: int = RESOLUTION_DPI,
    _scanimage: str = SCANIMAGE,
    _env: dict[str, str] | None = None,
) -> Path:
    """Scan one ADF job into inbox/<job>/<job>-NN.jpg; the job dir appears only on success."""
    job_dir = ensure_job_dir(inbox, job)
    env = _env if _env is not None else _sane_env()
    staging = Path(tempfile.mkdtemp(prefix=f"{job}-", dir=inbox))
    try:
        try:
            _ = subprocess.run(
                [
                    _scanimage,
                    "-d",
                    device,
                    "--source",
                    SOURCE_BY_MODE[mode],
                    "--mode",
                    "Color",
                    "--resolution",
                    str(resolution),
                    "--format",
                    "png",
                    "--batch=page-%d.png",
                ],
                cwd=staging,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = str(exc.stderr or exc.stdout or "").strip()
            raise ScanError(f"scan failed — check the ADF is loaded and the scanner is awake ({detail})") from exc

        pages = sorted(staging.glob("page-*.png"))
        if not pages:
            raise ScanError("scan produced no pages — check the ADF is loaded and the scanner is awake") from None
        for png in pages:
            number = int(png.stem.rsplit("-", 1)[1])  # page-1 -> 1; scanimage's %d is not zero-padded
            # the raw file name carries the batch id: if the user renames the
            # folder, any file still says which batch and position it belongs to
            Image.open(png).convert("RGB").save(png.with_name(f"{job}-{number:02d}.jpg"), quality=JPEG_QUALITY)
            png.unlink()
    except (ScanError, OSError):
        shutil.rmtree(staging, ignore_errors=True)  # best-effort; the inbox sees only complete jobs
        raise
    return staging.rename(job_dir)  # atomic: the inbox never sees a partial job


def register_batch(
    job: str,
    job_dir: Path,
    label: str,
    *,
    source: str = SCAN_SOURCE,
    registry_dir: Path = REGISTRY_DIR,
) -> Path:
    """The capture-side registry record: label, source, page hashes, status pending.

    The label is associated with the batch here — never written into the
    user's folder (MULTI-DOC-IMPORT-PRD.md R6).
    """
    pages = {page.name: hashlib.sha256(page.read_bytes()).hexdigest() for page in sorted(job_dir.glob("*.jpg"))}
    record = {
        "batch_id": job,
        "path": str(job_dir),
        "label": label,
        "source": source,
        "status": "pending",
        "arrived_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "pages": pages,
        "fingerprint": sorted(pages.values()),
        "boundaries": None,
    }
    registry_dir.mkdir(parents=True, exist_ok=True)
    record_path = registry_dir / f"{job}.json"
    atomic_write(record_path, json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    return record_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scan", description="Scan the Epson FF-680W into the user's scan area")
    parser.add_argument("mode", choices=MODES, help="what is in the ADF")
    parser.add_argument("--label", default="", help="the envelope/pile label (what's written on it)")
    parser.add_argument("--job", default="", help="scan folder name (default: scan-<timestamp>)")
    parser.add_argument("--inbox", type=Path, default=INBOX, help="the user's scan area (default: USER_SCAN_AREA)")
    parser.add_argument("--resolution", type=int, default=RESOLUTION_DPI, help="DPI (default: 300)")
    parser.add_argument("--device", default="", help="SANE device name (default: auto-pick the Epson device)")
    args = parser.parse_args(argv)

    try:
        job = args.job or f"scan-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}"
        label = args.label
        if not label and sys.stdin.isatty():
            label = input("Envelope/pile label (what's written on it)? blank for none: ").strip()
        try:
            listed = subprocess.run(
                [SCANIMAGE, "-L"], capture_output=True, text=True, check=True, env=_sane_env()
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            # scanimage missing, or SANE misconfigured — the same clean error
            # the other failure paths give, not a raw traceback (review, 2026-08-14)
            raise ScanError(f"{SCANIMAGE} -L failed ({exc}) — is the scanner connected and SANE configured?") from exc
        device = args.device or pick_device(parse_devices(listed))
        job_dir = scan_job(device, args.mode, job, inbox=args.inbox, resolution=args.resolution)
        record_path = register_batch(job, job_dir, label)
    except ScanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    pages = sorted(job_dir.glob("*.jpg"))
    print(f"scanned {len(pages)} page(s) -> {job_dir}")
    print(f"registered {len(pages)} page(s) -> {record_path}" + (f" (label: {label})" if label else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
