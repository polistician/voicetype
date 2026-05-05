"""paths.py — Resolve paths for Swift helper binaries in source-tree and bundled runs."""
import os
import sys


def helper_path(name: str) -> str:
    """Find a compiled Swift helper binary by name.

    Looks first inside the PyInstaller bundle (sys._MEIPASS) if running bundled,
    else falls back to the source tree at ~/voicetype/<name>.

    Args:
        name: Bare helper name (e.g. "hotkey_helper", not "/full/path/hotkey_helper").

    Returns:
        Absolute path to the helper binary.
    """
    # PyInstaller bundled mode
    if hasattr(sys, '_MEIPASS'):
        bundled = os.path.join(sys._MEIPASS, name)
        if os.path.exists(bundled):
            return bundled
        # Some bundlers put binaries one level up
        bundled_alt = os.path.join(os.path.dirname(sys._MEIPASS), name)
        if os.path.exists(bundled_alt):
            return bundled_alt

    # Source-tree mode
    return os.path.expanduser(f"~/voicetype/{name}")
