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
  VD_MODEL            HF repo id or local path of an MLX Whisper model
  VD_LANGUAGE         2-letter language code passed to Whisper
  VD_TRIGGER          key name from pynput.keyboard.Key (alt_r, f13, ctrl_r …)
  VD_INITIAL_PROMPT   short string biasing Whisper toward given vocabulary;
                      unset = use built-in PL/tech prompt, empty ("") = off
  VD_POSTPROCESS      "lmstudio" to pipe transcript through an
                      OpenAI-compatible local LLM (e.g. Bielik in LM Studio)
  VD_LMSTUDIO_URL     LM Studio endpoint (default http://localhost:1234/v1/chat/completions)
  VD_LMSTUDIO_MODEL   model id hint sent to LM Studio (default bielik)
"""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
import threading
import urllib.request
import urllib.error
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

DEFAULT_INITIAL_PROMPT = (
    "Claude Code, MLX, Whisper, launchd, LaunchAgent, plist, Python, pip, venv, "
    "git, repozytorium, commit, merge, pushować, schowek, Accessibility, "
    "Homebrew, terminal, config, transkrypcja, dyktowanie, skrypt, API, JSON."
)
INITIAL_PROMPT = os.environ.get("VD_INITIAL_PROMPT", DEFAULT_INITIAL_PROMPT) or None

POSTPROCESS = os.environ.get("VD_POSTPROCESS", "").lower()
LMSTUDIO_URL = os.environ.get(
    "VD_LMSTUDIO_URL", "http://localhost:1234/v1/chat/completions"
)
LMSTUDIO_MODEL = os.environ.get("VD_LMSTUDIO_MODEL", "bielik")
LMSTUDIO_SYSTEM = (
    "Jesteś edytorem polskiej transkrypcji z mowy. Popraw interpunkcję, "
    "wielkie litery na początku zdań i po kropce, usuń pauzy wahania typu "
    "'eee', 'yyy', 'no', 'znaczy'. BEZWZGLĘDNIE zachowaj dokładnie słowa "
    "wypowiedzi — nie parafrazuj, nie dodawaj treści, nie tłumacz. "
    "Zwróć TYLKO poprawiony tekst, bez komentarzy ani cudzysłowów."
)

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
            wav,
            path_or_hf_repo=MODEL,
            language=LANGUAGE,
            initial_prompt=INITIAL_PROMPT,
            verbose=False,
        )
    except Exception as e:
        print(f"[error] transcribe: {e}", file=sys.stderr)
        return
    finally:
        Path(wav).unlink(missing_ok=True)
    asr_dt = time.time() - t0

    text = res["text"].strip()
    llm_dt = 0.0
    if text and POSTPROCESS == "lmstudio":
        t1 = time.time()
        text = _lmstudio_cleanup(text)
        llm_dt = time.time() - t1

    timing = f"{asr_dt:.1f}s ASR"
    if llm_dt:
        timing += f" + {llm_dt:.1f}s LLM"
    print(f"✓ {duration:.1f}s audio → {timing}: {text!r}", flush=True)
    if not text:
        return

    pyperclip.copy(text)
    time.sleep(0.08)  # let the trigger-key release settle before sending ⌘V
    kb.press(keyboard.Key.cmd)
    kb.press("v")
    kb.release("v")
    kb.release(keyboard.Key.cmd)


def _lmstudio_cleanup(text: str, timeout: float = 8.0) -> str:
    """Send transcript through an OpenAI-compatible local LLM (LM Studio).

    Falls back to the original text on any failure so dictation keeps working
    when LM Studio is off, unreachable, or timing out.
    """
    payload = json.dumps({
        "model": LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": LMSTUDIO_SYSTEM},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        LMSTUDIO_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        cleaned = data["choices"][0]["message"]["content"].strip()
        return cleaned or text
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        print(f"[warn] LM Studio postprocess failed, keeping raw text: {e}", file=sys.stderr)
        return text


def _warmup() -> None:
    silence = np.zeros(int(SAMPLE_RATE * 0.5), dtype=np.float32)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, silence, SAMPLE_RATE)
        wav = tmp.name
    try:
        mlx_whisper.transcribe(
            wav,
            path_or_hf_repo=MODEL,
            language=LANGUAGE,
            initial_prompt=INITIAL_PROMPT,
            verbose=False,
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
    print(f"initial_prompt: {'on' if INITIAL_PROMPT else 'off'}"
          f"  | postprocess: {POSTPROCESS or 'off'}"
          + (f" ({LMSTUDIO_URL})" if POSTPROCESS == "lmstudio" else ""))
    print("Warming up model…", flush=True)
    _warmup()
    print(f"Ready. Hold {TRIGGER_NAME} to talk. Ctrl-C to quit.\n", flush=True)
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
