"""Platform paths, config file locations, stdout redirect helper.

Everything that depends on where the OS puts user data / logs lives here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_support_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "voice-dictate"
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "voice-dictate"
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


def _log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs"
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "voice-dictate" / "logs"
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


APP_SUPPORT_DIR = _app_support_dir()
CONFIG_PATH = APP_SUPPORT_DIR / "config.json"
PRESETS_PATH = APP_SUPPORT_DIR / "presets.json"
RECORDING_FLAG = APP_SUPPORT_DIR / "recording.flag"
LOG_DIR = _log_dir()


def redirect_std_to_log() -> None:
    """Point sys.stdout/sys.stderr at the log files. Windows only.

    macOS uses the LaunchAgent plist's StandardOutPath/StandardErrorPath for
    this at the file-descriptor level; calling this function there would
    create a second Python-level buffer and invite interleaving.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sys.stdout = open(LOG_DIR / "voice_dictate.log", "a", buffering=1, encoding="utf-8")
    sys.stderr = open(LOG_DIR / "voice_dictate.err.log", "a", buffering=1, encoding="utf-8")
