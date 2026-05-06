"""updater.py — In-app updater for VoiceType.

Downloads the latest VoiceType.dmg from GitHub Releases, verifies SHA256
against the published .sha256 sidecar, replaces /Applications/VoiceType.app,
and relaunches.

Designed for ad-hoc-signed bundles. macOS *may* require Accessibility/
Microphone re-grants after the swap because the signature changes per
release — that's an unavoidable Apple-side constraint until notarization.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from typing import Callable, Optional


REPO = "polistician/voicetype"
APP_PATH = "/Applications/VoiceType.app"
DMG_URL = f"https://github.com/{REPO}/releases/latest/download/VoiceType.dmg"
SHA_URL = f"https://github.com/{REPO}/releases/latest/download/VoiceType.dmg.sha256"
TMP_ROOT = os.path.expanduser("~/.voicetype/.update_tmp")
MOUNT_POINT = "/Volumes/VoiceType"


class UpdateError(Exception):
    pass


def _download(url: str, dest: str, on_progress: Optional[Callable[[int, int], None]] = None) -> None:
    """Stream-download a URL to dest. on_progress(bytes_downloaded, total_bytes)."""
    with urllib.request.urlopen(url, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def _detach_mount() -> None:
    """Force-detach the VoiceType DMG mount point if present (idempotent)."""
    if os.path.exists(MOUNT_POINT):
        _run(["hdiutil", "detach", MOUNT_POINT, "-force"])


def perform_update(on_progress: Optional[Callable[[str], None]] = None) -> str:
    """Download + verify + install + return the new version string.
    Raises UpdateError on any failure."""
    def status(s: str) -> None:
        if on_progress:
            on_progress(s)

    # Clean any leftover tmp from a previous failed run
    if os.path.exists(TMP_ROOT):
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    os.makedirs(TMP_ROOT, exist_ok=True)

    dmg_path = os.path.join(TMP_ROOT, "VoiceType.dmg")
    sha_path = os.path.join(TMP_ROOT, "VoiceType.dmg.sha256")

    try:
        # 1. Download DMG with per-percent progress
        status("Downloading 0%…")
        last_pct: list[int] = [-1]  # mutable cell for nonlocal-free closure

        def _dl_progress(downloaded: int, total: int) -> None:
            if total:
                pct = int(100 * downloaded / total)
                if pct != last_pct[0]:
                    last_pct[0] = pct
                    mb_done = downloaded / (1024 * 1024)
                    mb_total = total / (1024 * 1024)
                    status(f"Downloading {pct}% ({mb_done:.0f}/{mb_total:.0f} MB)")

        _download(DMG_URL, dmg_path, on_progress=_dl_progress)

        # 2. Download SHA sidecar
        status("Downloading checksum…")
        _download(SHA_URL, sha_path)

        # 3. Verify
        status("Verifying download…")
        with open(sha_path) as f:
            published = f.read().strip().split()[0]
        actual = _sha256(dmg_path)
        if published != actual:
            raise UpdateError(f"SHA256 mismatch (downloaded {actual[:12]}…, expected {published[:12]}…). Refusing to install a corrupted DMG.")

        # 4. Mount
        status("Mounting…")
        _detach_mount()
        proc = _run(["hdiutil", "attach", "-nobrowse", "-noverify", "-quiet", dmg_path])
        if proc.returncode != 0:
            raise UpdateError(f"Could not mount DMG: {proc.stderr.strip() or 'unknown error'}")

        # 5. Find the .app inside the mounted volume (volume name might vary)
        candidate = os.path.join(MOUNT_POINT, "VoiceType.app")
        if not os.path.isdir(candidate):
            import glob
            matches = glob.glob("/Volumes/VoiceType*/VoiceType.app")
            if matches:
                candidate = matches[0]
            else:
                raise UpdateError("VoiceType.app not found in mounted DMG.")

        # 6. Replace /Applications/VoiceType.app
        status("Installing…")
        if os.path.exists(APP_PATH):
            shutil.rmtree(APP_PATH, ignore_errors=False)
        shutil.copytree(candidate, APP_PATH, symlinks=True)

        # 7. xattr cleanup
        _run(["xattr", "-dr", "com.apple.quarantine", APP_PATH])

        # 8. Read new version
        info = os.path.join(APP_PATH, "Contents", "Info.plist")
        new_version = "?"
        try:
            v = _run(["plutil", "-extract", "CFBundleShortVersionString", "raw", info])
            if v.returncode == 0:
                new_version = v.stdout.strip()
        except Exception:
            pass

        status(f"Updated to v{new_version}")
        return new_version

    finally:
        # Always detach + cleanup tmp
        status("Cleaning up…")
        _detach_mount()
        shutil.rmtree(TMP_ROOT, ignore_errors=True)


def relaunch() -> None:
    """Open the (new) installed app and exit current process."""
    subprocess.Popen(["open", APP_PATH])
    sys.exit(0)
