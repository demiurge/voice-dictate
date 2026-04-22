"""MLX Whisper backend for macOS (Apple Silicon only)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import mlx_whisper

from core.transcriber import Transcriber


_SAMPLE_RATE = 16000


class MLXWhisperTranscriber(Transcriber):
    def __init__(self, model: str, language: str, initial_prompt: str | None) -> None:
        self.model = model
        self.language = language
        self.initial_prompt = initial_prompt

    def transcribe(self, wav_path: str) -> str:
        res = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=self.model,
            language=self.language,
            initial_prompt=self.initial_prompt,
            verbose=False,
        )
        return res["text"].strip()

    def warmup(self) -> None:
        silence = np.zeros(int(_SAMPLE_RATE * 0.5), dtype=np.float32)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, silence, _SAMPLE_RATE)
            wav = tmp.name
        try:
            self.transcribe(wav)
        finally:
            Path(wav).unlink(missing_ok=True)
