"""Tests for the FF-680W scan tool: device selection, job-dir guard, the
scanimage -L parser, and the capture-side registry record — the
deterministic contracts; the scan itself is hardware-bound and calibrated
on the device (TECH-SPEC §16.8)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.scan import ScanError, ensure_job_dir, parse_devices, pick_device, register_batch

SCANIMAGE_L = """device `v4l:/dev/video0' is a Noname USB2.0 VGA UVC WebCam: USB2.0 V virtual device
device `epsonds:libusb:002:004' is a Epson FF-680W ESC/I-2
device `airscan:e0:EPSON FF-680W' is a eSCL EPSON FF-680W ip=192.168.1.178
device `airscan:w1:HP OfficeJet' is a WSD HP OfficeJet scanner
"""


def test_parse_devices_reads_every_device_line() -> None:
    assert parse_devices(SCANIMAGE_L) == [
        "v4l:/dev/video0",
        "epsonds:libusb:002:004",
        "airscan:e0:EPSON FF-680W",
        "airscan:w1:HP OfficeJet",
    ]


def test_parse_devices_empty_output() -> None:
    assert parse_devices("") == []


def test_pick_device_prefers_local_usb_epson() -> None:
    devices = ["airscan:e0:EPSON FF-680W", "epsonds:libusb:002:004"]
    assert pick_device(devices) == "epsonds:libusb:002:004"


def test_pick_device_prefers_epson_airscan_over_other_airscan() -> None:
    assert pick_device(["airscan:w1:HP OfficeJet", "airscan:e0:EPSON FF-680W"]) == "airscan:e0:EPSON FF-680W"


def test_pick_device_falls_back_to_any_airscan() -> None:
    assert pick_device(["airscan:w1:HP OfficeJet"]) == "airscan:w1:HP OfficeJet"


def test_pick_device_rejects_no_scanner() -> None:
    with pytest.raises(ScanError, match="no scanner found"):
        _ = pick_device(["v4l:/dev/video0"])
    with pytest.raises(ScanError, match="no scanner found"):
        _ = pick_device([])


def test_ensure_job_dir_creates_inbox_and_returns_job_path(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    job_dir = ensure_job_dir(inbox, "Box-1-Letters-1977")
    assert job_dir == inbox / "Box-1-Letters-1977"
    assert inbox.is_dir()
    assert not job_dir.exists()  # materialised by the caller (scan_job's atomic rename)


def test_ensure_job_dir_rejects_bad_names(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    for bad in ("", ".", "..", "a/b", "a\\b", "Box 1", "scan-01!"):
        with pytest.raises(ScanError, match="letters, digits, or hyphens"):
            _ = ensure_job_dir(inbox, bad)


def test_ensure_job_dir_allows_existing_empty_job(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    job_dir = ensure_job_dir(inbox, "job")
    job_dir.mkdir()
    assert ensure_job_dir(inbox, "job") == job_dir


def test_ensure_job_dir_refuses_non_empty_job(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    job_dir = ensure_job_dir(inbox, "job")
    job_dir.mkdir()
    _ = (job_dir / "page-01.jpg").write_bytes(b"x")
    with pytest.raises(ScanError, match="append-only"):
        _ = ensure_job_dir(inbox, "job")


def _fake_scanimage(script: str, tmp_path: Path) -> str:
    """A fake `scanimage` executable; scan_job runs it with cwd=staging."""
    import stat

    fake = tmp_path / "fake-scanimage"
    fake.write_text(script)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return str(fake)


def test_scan_job_converts_pages_to_zero_padded_jpegs(tmp_path: Path) -> None:
    from PIL import Image

    from tools.scan import scan_job

    source = tmp_path / "source"
    source.mkdir()
    for n in (1, 2, 10):
        Image.new("RGB", (8, 8), (255, 0, 0)).save(source / f"page-{n}.png")
    fake = _fake_scanimage(f"#!/bin/sh\ncp {source}/*.png .\n", tmp_path)

    inbox = tmp_path / "inbox"
    job_dir = scan_job("epsonds:libusb:fake", "docs", "job", inbox=inbox, _scanimage=fake, _env={})

    assert sorted(p.name for p in job_dir.glob("*.jpg")) == ["job-01.jpg", "job-02.jpg", "job-10.jpg"]
    assert list(job_dir.glob("*.png")) == []  # staging pngs never reach the inbox


def test_scan_job_failure_cleans_up_and_raises(tmp_path: Path) -> None:
    from tools.scan import scan_job

    fake = _fake_scanimage("#!/bin/sh\necho 'boom' >&2\nexit 1\n", tmp_path)
    inbox = tmp_path / "inbox"

    with pytest.raises(ScanError, match="scan failed"):
        _ = scan_job("epsonds:libusb:fake", "docs", "job", inbox=inbox, _scanimage=fake, _env={})
    assert list(inbox.iterdir()) == []  # no job dir, no staging leftovers


def test_scan_job_no_pages_cleans_up_and_raises(tmp_path: Path) -> None:
    from tools.scan import scan_job

    fake = _fake_scanimage("#!/bin/sh\nexit 0\n", tmp_path)  # scanner runs, ADF empty
    inbox = tmp_path / "inbox"

    with pytest.raises(ScanError, match="no pages"):
        _ = scan_job("epsonds:libusb:fake", "docs", "job", inbox=inbox, _scanimage=fake, _env={})
    assert list(inbox.iterdir()) == []


def test_register_batch_writes_label_hashes_and_status(tmp_path: Path) -> None:
    from PIL import Image

    job_dir = tmp_path / "scan-20260813-1850"
    job_dir.mkdir()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(job_dir / "scan-20260813-1850-01.jpg", quality=88)
    Image.new("RGB", (8, 8), (0, 255, 0)).save(job_dir / "scan-20260813-1850-02.jpg", quality=88)

    registry = tmp_path / "registry"
    record_path = register_batch("scan-20260813-1850", job_dir, "Box-1-Letters-1977", registry_dir=registry)

    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["batch_id"] == "scan-20260813-1850"
    assert record["label"] == "Box-1-Letters-1977"
    assert record["source"] == "epson-ff680w"
    assert record["status"] == "pending"
    assert sorted(record["pages"]) == ["scan-20260813-1850-01.jpg", "scan-20260813-1850-02.jpg"]
    assert record["fingerprint"] == sorted(record["pages"].values())
    assert (
        record["pages"]["scan-20260813-1850-01.jpg"]
        == hashlib.sha256((job_dir / "scan-20260813-1850-01.jpg").read_bytes()).hexdigest()
    )
    assert job_dir.name == "scan-20260813-1850"  # the label never touches the folder name
    assert list(registry.glob(".*.tmp")) == []  # atomic write leaves no temp siblings
