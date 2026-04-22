"""Push-to-talk audio recorder. One active session at a time."""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


SAMPLE_RATE = 16000
CHANNELS = 1
MIN_DURATION_S = 0.3


class AudioRecorder:
    """Thread-safe push-to-talk recorder. Not reentrant."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._start_ts = 0.0

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        self._frames.append(indata.copy())

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> bool:
        """Begin a new recording. Returns False if already recording."""
        with self._lock:
            if self._recording:
                return False
            self._recording = True
            self._frames = []
            self._start_ts = time.time()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
        return True

    def stop(self) -> tuple[str | None, float]:
        """Stop recording and dump to WAV. Returns (wav_path, duration_s).

        Returns (None, duration) if the utterance was under MIN_DURATION_S or
        produced no frames. Caller owns the WAV path and must unlink it.
        """
        with self._lock:
            if not self._recording:
                return None, 0.0
            self._recording = False
            stream = self._stream
            stream.stop()
            stream.close()
            frames = self._frames
            duration = time.time() - self._start_ts

        if duration < MIN_DURATION_S or not frames:
            return None, duration

        audio = np.concatenate(frames, axis=0).flatten().astype(np.float32)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio, SAMPLE_RATE)
            return tmp.name, duration
