"""Abstract Transcriber + platform-dispatched factory.

Implementations live under platform_*/transcriber_*.py. The factory picks
one based on VD_ASR_BACKEND or sys.platform (mlx on darwin, faster-whisper
on win32).
"""
from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, wav_path: str) -> str: ...

    @abstractmethod
    def warmup(self) -> None: ...


def load_transcriber(
    model: str, *, language: str, initial_prompt: str | None
) -> Transcriber:
    backend = os.environ.get("VD_ASR_BACKEND")
    if backend is None:
        backend = "mlx" if sys.platform == "darwin" else "faster-whisper"
    if backend == "mlx":
        from platform_mac.transcriber_mlx import MLXWhisperTranscriber
        return MLXWhisperTranscriber(model, language, initial_prompt)
    if backend == "faster-whisper":
        from platform_win.transcriber_fw import FasterWhisperTranscriber
        return FasterWhisperTranscriber(model, language, initial_prompt)
    raise ValueError(f"Unknown VD_ASR_BACKEND: {backend}")
