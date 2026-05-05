# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for VoiceType.app
import os
import subprocess

HOME = os.path.expanduser("~/voicetype")
MODELS_DIR = os.path.join(HOME, "models")
VERSION = open(os.path.join(HOME, "VERSION")).read().strip()

# Collect any whisper.cpp model present (could be base.en, small, etc.)
model_files = []
if os.path.isdir(MODELS_DIR):
    for f in os.listdir(MODELS_DIR):
        if f.startswith("ggml-") and f.endswith(".bin"):
            model_files.append((os.path.join(MODELS_DIR, f), "models"))

# Compiled Swift helpers — only include if they exist
swift_helpers = []
for h in ["hotkey_helper", "paste_helper", "snippet_overlay",
          "settings_window", "onboarding", "keys_helper"]:
    p = os.path.join(HOME, h)
    if os.path.exists(p):
        swift_helpers.append((p, "."))

a = Analysis(
    [os.path.join(HOME, "voxtype.py")],
    pathex=[HOME],
    binaries=swift_helpers,
    datas=model_files + [
        (os.path.join(HOME, "assets", "menubar-mic.pdf"), "assets"),
    ] if os.path.exists(os.path.join(HOME, "assets", "menubar-mic.pdf")) else model_files,
    hiddenimports=[
        "pywhispercpp", "pywhispercpp.model",
        "rumps", "sounddevice",
        "rapidfuzz", "rapidfuzz.fuzz",
        "numpy",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "torchaudio", "torchvision",
        "transformers", "sentence_transformers",
        "tokenizers",
        "scipy",
        "PIL", "matplotlib",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceType",
    debug=False,
    strip=False,
    upx=False,
    console=False,           # menubar-only app
    argv_emulation=True,
    target_arch=None,
    codesign_identity="-",   # ad-hoc
    entitlements_file=None,
    icon=os.path.join(HOME, "assets", "app-icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VoiceType",
)

import sys as _sys
# Post-COLLECT: re-sign Python.framework without hardened runtime so macOS
# allows it to be mapped into the non-platform bootloader process. Without
# this, dlopen fails with "Team IDs differ" on Python 3.14 (Homebrew).
_dist_app = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "..", "dist", "VoiceType.app")
_py_fw = os.path.join(_dist_app, "Contents", "Frameworks", "Python.framework",
                      "Versions", "3.14", "Python")
if os.path.exists(_py_fw):
    subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", _py_fw], check=False)
    subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none",
                    "--deep", _dist_app], check=False)

app = BUNDLE(
    coll,
    name="VoiceType.app",
    icon=os.path.join(HOME, "assets", "app-icon.icns"),
    bundle_identifier="com.polistician.voicetype",
    info_plist={
        "CFBundleName": "VoiceType",
        "CFBundleDisplayName": "VoiceType",
        "CFBundleExecutable": "VoiceType",
        "CFBundleIdentifier": "com.polistician.voicetype",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": "VoiceType records audio when you hold ⌥ C, transcribes it locally, and pastes the text.",
        "NSAppleEventsUsageDescription": "VoiceType uses Accessibility events to press ⌘ V on your behalf.",
        "NSHumanReadableCopyright": "MIT — see LICENSE file. Copyright © 2026 Beauregard Berton.",
    },
)
