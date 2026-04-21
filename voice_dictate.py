#!/usr/bin/env python3
"""Push-to-talk voice dictation using MLX Whisper (macOS, Apple Silicon).

Hold a trigger key to record audio from the default microphone, release to
transcribe with Whisper and paste the result into the currently focused
window via Cmd+V.

Defaults:
  trigger key  : right Option (⌥)
  model        : mlx-community/whisper-large-v3-turbo
  language     : pl

Runtime config (managed by the menu bar app, overrides env vars):
  ~/Library/Application Support/voice-dictate/config.json
  ~/Library/Application Support/voice-dictate/presets.json

Override with environment variables (used as fallbacks when no runtime config):
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
    "Claude Code, MLX, Whisper, Bielik, launchd, LaunchAgent, plist, Python, "
    "pip, venv, git, repozytorium, commit, merge, pushować, schowek, "
    "Accessibility, Homebrew, terminal, config, transkrypcja, dyktowanie, "
    "skrypt, API, JSON, LM Studio."
)
INITIAL_PROMPT = os.environ.get("VD_INITIAL_PROMPT", DEFAULT_INITIAL_PROMPT) or None

POSTPROCESS = os.environ.get("VD_POSTPROCESS", "").lower()
LMSTUDIO_URL = os.environ.get(
    "VD_LMSTUDIO_URL", "http://localhost:1234/v1/chat/completions"
)
LMSTUDIO_MODEL = os.environ.get("VD_LMSTUDIO_MODEL", "bielik")

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "voice-dictate"
CONFIG_PATH = APP_SUPPORT_DIR / "config.json"
PRESETS_PATH = APP_SUPPORT_DIR / "presets.json"
LMSTUDIO_SYSTEM = (
    "Jesteś edytorem polskiej transkrypcji z mowy (wyjście ASR typu Whisper). "
    "Twoje zadania:\n"
    "1) Popraw interpunkcję i wielkie litery (początek zdań, po kropce, nazwy własne).\n"
    "2) Usuń wahania ('eee', 'yyy', 'no', 'znaczy').\n"
    "3) Jeśli fragment tekstu NIE ma sensu po polsku i wygląda na fonetyczne "
    "przekręcenie przez ASR (np. 'Wons Bielik', 'Wąsobygelka', 'klałd kot', "
    "'launczdi'), zastąp go najbardziej prawdopodobnym poprawnym polskim "
    "wyrażeniem o tym samym brzmieniu (np. 'Włącz Bielika', 'Claude Code', "
    "'launchd'). Kontekst: użytkownik dyktuje krótkie komendy i fragmenty "
    "kodu/technologii (Claude Code, MLX, Whisper, Bielik, launchd, git, "
    "Python, LM Studio).\n\n"
    "ZASADY ŻELAZNE:\n"
    "• NIE parafrazuj, NIE dodawaj treści, NIE tłumacz na inny język.\n"
    "• Jeśli tekst jest sensowny po polsku — zostaw słowa DOKŁADNIE jak są, "
    "zmień tylko interpunkcję i wielkość liter.\n"
    "• Jeśli nie masz pewności czy to błąd ASR czy celowa wypowiedź — zostaw.\n"
    "• Zwróć TYLKO końcowy tekst, bez komentarzy, wyjaśnień, cudzysłowów."
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
    pp_cfg = _resolve_postprocess_config()
    if text and pp_cfg is not None:
        t1 = time.time()
        text = _lmstudio_cleanup(text, pp_cfg)
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


def _resolve_postprocess_config() -> dict | None:
    """Figure out whether post-processing is on and which endpoint/model to use.

    Resolution order:
      1. Runtime config files (written by the menu bar app).
      2. Legacy env vars (VD_POSTPROCESS=lmstudio + VD_LMSTUDIO_*).
      3. None -> post-processing disabled.

    Returns a dict with keys ``url``, ``model``, ``system_prompt`` or None.
    """
    try:
        if CONFIG_PATH.exists() and PRESETS_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text())
            if not cfg.get("postprocess"):
                return None
            presets = json.loads(PRESETS_PATH.read_text())
            active_id = cfg.get("active_preset")
            preset = next((p for p in presets if p.get("id") == active_id), None)
            if preset is None:
                return None
            model = cfg.get("current_model") or preset.get("default_model")
            if not model:
                return None
            base = (preset.get("base_url") or "").rstrip("/")
            if not base:
                return None
            return {
                "url": base + "/chat/completions",
                "model": model,
                "system_prompt": preset.get("system_prompt") or LMSTUDIO_SYSTEM,
            }
    except (json.JSONDecodeError, OSError, KeyError) as e:
        print(f"[warn] runtime config unreadable, falling back to env: {e}",
              file=sys.stderr)

    if POSTPROCESS == "lmstudio":
        return {
            "url": LMSTUDIO_URL,
            "model": LMSTUDIO_MODEL,
            "system_prompt": LMSTUDIO_SYSTEM,
        }
    return None


def _lmstudio_cleanup(text: str, cfg: dict, timeout: float = 8.0) -> str:
    """Send transcript through an OpenAI-compatible local LLM.

    Falls back to the original text on any failure so dictation keeps working
    when the endpoint is off, unreachable, or timing out.
    """
    payload = json.dumps({
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": cfg["system_prompt"]},
            {"role": "user", "content": text},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        cfg["url"],
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        cleaned = data["choices"][0]["message"]["content"].strip()
        return cleaned or text
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        print(f"[warn] postprocess failed, keeping raw text: {e}", file=sys.stderr)
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
    pp_cfg = _resolve_postprocess_config()
    if pp_cfg is not None:
        pp_desc = f"on ({pp_cfg['model']} @ {pp_cfg['url']})"
    else:
        pp_desc = "off"
    cfg_source = "runtime config" if CONFIG_PATH.exists() else "env vars"
    print(f"initial_prompt: {'on' if INITIAL_PROMPT else 'off'}"
          f"  | postprocess: {pp_desc}  [source: {cfg_source}]")
    print("Warming up model…", flush=True)
    _warmup()
    print(f"Ready. Hold {TRIGGER_NAME} to talk. Ctrl-C to quit.\n", flush=True)
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
