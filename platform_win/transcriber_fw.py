"""faster-whisper backend for Windows (NVIDIA CUDA).

Requires CUDA 12 + cuDNN 9 DLLs. We install these as pip packages
(nvidia-cublas-cu12, nvidia-cudnn-cu12); _bootstrap_cuda_dlls() adds their
bin directories to the DLL search path. Must be called BEFORE the first
`from faster_whisper import ...`.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from core.transcriber import Transcriber


_SAMPLE_RATE = 16000


def _bootstrap_cuda_dlls() -> None:
    import nvidia.cublas
    import nvidia.cudnn

    for pkg in (nvidia.cublas, nvidia.cudnn):
        # nvidia.* are PEP 420 namespace packages — __file__ is None, use __path__.
        bin_dir = os.path.join(pkg.__path__[0], "bin")
        if os.path.isdir(bin_dir):
            os.add_dll_directory(bin_dir)


class FasterWhisperTranscriber(Transcriber):
    def __init__(self, model: str, language: str, initial_prompt: str | None) -> None:
        _bootstrap_cuda_dlls()
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model, device="cuda", compute_type="float16")
        self.language = language
        self.initial_prompt = initial_prompt

    def transcribe(self, wav_path: str) -> str:
        segments, _ = self.model.transcribe(
            wav_path,
            language=self.language,
            initial_prompt=self.initial_prompt,
            beam_size=5,
        )
        return "".join(s.text for s in segments).strip()

    def warmup(self) -> None:
        silence = np.zeros(int(_SAMPLE_RATE * 0.5), dtype=np.float32)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, silence, _SAMPLE_RATE)
            wav = tmp.name
        try:
            self.transcribe(wav)
        finally:
            Path(wav).unlink(missing_ok=True)
