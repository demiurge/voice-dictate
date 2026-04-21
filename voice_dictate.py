#!/usr/bin/env python3
"""Push-to-talk voice dictation using MLX Whisper (macOS, Apple Silicon).

Hold a trigger key to record audio from the default microphone, release to
transcribe with Whisper and paste the result into the currently focused
window via Cmd+V.

Defaults:
  trigger key  : right Option (⌥)
  model        : mlx-community/whisper-large-v3-turbo
  language     : pl

Override with environment variables:
  VD_MODEL     : HuggingFace repo id or local path of an MLX Whisper model
  VD_LANGUAGE  : 2-letter language code passed to Whisper
  VD_TRIGGER   : key name from pynput.keyboard.Key (e.g. alt_r, f13, ctrl_r)
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import threading
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import pyperclip
from pynput import keyboard
import mlx_whisper

MODEL = os.environ.get("VD_MODEL", "mlx-community/whisper-large-v3-turbo")
LANGUAGE = os.environ.get("VD_LANGUAGE", "pl")
TRIGGER_NAME = os.environ.get("VD_TRIGGER", "alt_r")
TRIGGER_KEY = getattr(keyboard.Key, TRIGGER_NAME)

SAMPLE_RATE = 16000
CHANNELS = 1
MIN_DURATION_S = 0.3

kb = keyboard.Controller()
lock = threading.Lock()
state: dict = {"recording": False, "frames": [], "stream": None, "start": 0.0}


def _cb(indata, frames, time_info, status) -> None:
    if status:
        print(f"[audio] {status}", file=sys.stderr)
    state["frames"].append(indata.copy())


def start_recording() -> None:
    with lock:
        if state["recording"]:
            return
        state["recording"] = True
        state["frames"] = []
        state["start"] = time.time()
        state["stream"] = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=_cb,
        )
        state["stream"].start()
    print("● rec…", flush=True)


def stop_and_transcribe() -> None:
    with lock:
        if not state["recording"]:
            return
        state["recording"] = False
        stream = state["stream"]
        stream.stop()
        stream.close()
        frames = state["frames"]
        duration = time.time() - state["start"]

    if duration < MIN_DURATION_S or not frames:
        print("… too short, skipped", flush=True)
        return

    audio = np.concatenate(frames, axis=0).flatten().astype(np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio, SAMPLE_RATE)
        wav = tmp.name

    t0 = time.time()
    try:
        res = mlx_whisper.transcribe(
            wav, path_or_hf_repo=MODEL, language=LANGUAGE, verbose=False
        )
    except Exception as e:
        print(f"[error] transcribe: {e}", file=sys.stderr)
        return
    finally:
        Path(wav).unlink(missing_ok=True)

    text = res["text"].strip()
    print(f"✓ {duration:.1f}s audio → {time.time() - t0:.1f}s ASR: {text!r}", flush=True)
    if not text:
        return

    pyperclip.copy(text)
    time.sleep(0.08)  # let the trigger-key release settle before sending ⌘V
    kb.press(keyboard.Key.cmd)
    kb.press("v")
    kb.release("v")
    kb.release(keyboard.Key.cmd)


def _warmup() -> None:
    silence = np.zeros(int(SAMPLE_RATE * 0.5), dtype=np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, silence, SAMPLE_RATE)
        wav = tmp.name
    try:
        mlx_whisper.transcribe(
            wav, path_or_hf_repo=MODEL, language=LANGUAGE, verbose=False
        )
    finally:
        Path(wav).unlink(missing_ok=True)


def on_press(key) -> None:
    if key == TRIGGER_KEY:
        start_recording()


def on_release(key) -> None:
    if key == TRIGGER_KEY:
        threading.Thread(target=stop_and_transcribe, daemon=True).start()


def main() -> None:
    print(f"Model: {MODEL}  | language: {LANGUAGE}  | trigger: {TRIGGER_NAME}")
    print("Warming up model…", flush=True)
    _warmup()
    print(f"Ready. Hold {TRIGGER_NAME} to talk. Ctrl-C to quit.\n", flush=True)
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
