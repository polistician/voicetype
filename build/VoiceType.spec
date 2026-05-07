# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for VoiceType.app
import os
import subprocess

HOME = os.path.expanduser("~/voicetype")
MODELS_DIR = os.path.join(HOME, "models")
VERSION = open(os.path.join(HOME, "VERSION")).read().strip()

# Bundle only large-v3-turbo — avoids shipping multiple 800 MB+ models if the
# old base.en still exists locally. Explicit list instead of glob.
model_files = []
DEFAULT_MODEL = "ggml-large-v3-turbo.bin"
if os.path.isfile(os.path.join(MODELS_DIR, DEFAULT_MODEL)):
    model_files.append((os.path.join(MODELS_DIR, DEFAULT_MODEL), "models"))

# Bundle Silero VAD ONNX model
if os.path.isfile(os.path.join(MODELS_DIR, "silero_vad.onnx")):
    model_files.append((os.path.join(MODELS_DIR, "silero_vad.onnx"), "models"))

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
        (os.path.join(HOME, "VERSION"), "."),
    ] if os.path.exists(os.path.join(HOME, "assets", "menubar-mic.pdf")) else model_files + [
        (os.path.join(HOME, "VERSION"), "."),
    ],
    hiddenimports=[
        "pywhispercpp", "pywhispercpp.model",
        "rumps", "sounddevice",
        "rapidfuzz", "rapidfuzz.fuzz",
        "numpy",
        "onnxruntime",
        # Lazy imports — these are imported inside method bodies so PyInstaller's
        # static analyzer misses them. Forcing inclusion here.
        "updater",  # voxtype.py: _perform_update_async -> from updater import ...
        "keys",     # translator.py: _get_key -> from keys import KeyStore
        "vad",      # voxtype.py: _get_vad -> from vad import SileroVAD
        "integrator_chat",  # voxtype.py: line 9 top-level import
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
    name="VoiceType_main",
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
    name="VoiceType_main",
)

import sys as _sys
import shutil as _shutil
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
        "CFBundleExecutable": "VoiceType",   # the launcher shim
        "CFBundleIdentifier": "com.polistician.voicetype",
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": "VoiceType records audio when you hold ⌥ C, transcribes it locally, and pastes the text.",
        "NSAppleEventsUsageDescription": "VoiceType uses Accessibility events to press ⌘ V on your behalf.",
        "NSHumanReadableCopyright": "MIT — see LICENSE file. Copyright © 2026 Beauregard Berton.",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "LSItemContentTypes": [],
        "NSSupportsAutomaticTermination": False,
        "NSSupportsSuddenTermination": False,
        # Make sure Spotlight knows this is an app, not just a bundle
        "CFBundlePackageType": "APPL",
    },
)

# Post-BUNDLE: install the AppTranslocation launcher shim.
# PyInstaller wrote MacOS/VoiceType_main (the Python entry). We copy our
# pre-compiled Swift launcher to MacOS/VoiceType so macOS launches it first.
_launcher_src = os.path.join(HOME, "voicetype_launcher")
_launcher_dst = os.path.join(_dist_app, "Contents", "MacOS", "VoiceType")
if os.path.exists(_launcher_src):
    _shutil.copy2(_launcher_src, _launcher_dst)
    os.chmod(_launcher_dst, 0o755)
    subprocess.run(
        ["codesign", "--sign", "-", "--force", "--timestamp=none", _launcher_dst],
        check=True,
    )
    print(f"[launcher] installed and signed: {_launcher_dst}")
else:
    print(f"[launcher] WARNING: {_launcher_src} not found — skipping launcher install")
    print("[launcher] Run: swiftc -O voicetype_launcher.swift -o voicetype_launcher")
