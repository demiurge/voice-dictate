"""Cross-platform recording-state signal via a file flag.

Daemon calls mark_recording_start() when the trigger key goes down and
mark_recording_end() in the finally block of the transcription pipeline.
The Windows tray polls is_recording() every ~100 ms to flip its icon. The
macOS Swift menu bar does not read the flag — it continues to tail the log
file, and writing the flag on macOS is a harmless no-op from its perspective.
"""
from __future__ import annotations

from core.config import APP_SUPPORT_DIR, RECORDING_FLAG


def mark_recording_start() -> None:
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    RECORDING_FLAG.touch(exist_ok=True)


def mark_recording_end() -> None:
    RECORDING_FLAG.unlink(missing_ok=True)


def is_recording() -> bool:
    return RECORDING_FLAG.exists()
