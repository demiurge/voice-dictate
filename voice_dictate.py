#!/usr/bin/env python3
"""Push-to-talk voice dictation — cross-platform entrypoint.

Hold a trigger key to record, release to transcribe with Whisper and paste
into the focused window.

Runtime config (managed by the tray / menu bar app, overrides env vars):
  macOS:   ~/Library/Application Support/voice-dictate/{config,presets}.json
  Windows: %APPDATA%\\voice-dictate\\{config,presets}.json

Env vars (fallbacks):
  VD_MODEL            HF repo id or local path of the ASR model
  VD_LANGUAGE         2-letter language code (default: pl)
  VD_TRIGGER          key name from pynput.keyboard.Key
                      (default: alt_r on macOS, ctrl_r on Windows)
  VD_INITIAL_PROMPT   short string biasing Whisper; "" to disable
  VD_POSTPROCESS      "lmstudio" to enable LLM cleanup via env fallback
  VD_LMSTUDIO_URL     OpenAI-compatible chat/completions endpoint
  VD_LMSTUDIO_MODEL   model id hint sent to the endpoint
  VD_ASR_BACKEND      "mlx" or "faster-whisper" (override platform default)
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from pynput import keyboard

from core.audio import AudioRecorder
from core.config import CONFIG_PATH
from core.postprocess import lmstudio_cleanup, resolve_postprocess_config
from core.transcriber import load_transcriber


if sys.platform == "darwin":
    from platform_mac.hotkey import default_trigger
    from platform_mac.paste import paste_text

    DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
elif sys.platform == "win32":
    from core.config import redirect_std_to_log
    from platform_win.hotkey import default_trigger
    from platform_win.paste import paste_text

    DEFAULT_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"
    redirect_std_to_log()
else:
    raise RuntimeError(f"Unsupported platform: {sys.platform}")


DEFAULT_INITIAL_PROMPT = (
    "Claude Code, MLX, Whisper, Bielik, launchd, LaunchAgent, plist, Python, "
    "pip, venv, git, repozytorium, commit, merge, pushować, schowek, "
    "Accessibility, Homebrew, terminal, config, transkrypcja, dyktowanie, "
    "skrypt, API, JSON, LM Studio."
)

MODEL = os.environ.get("VD_MODEL") or DEFAULT_MODEL
LANGUAGE = os.environ.get("VD_LANGUAGE", "pl")
PROMPT = os.environ.get("VD_INITIAL_PROMPT", DEFAULT_INITIAL_PROMPT) or None
TRIGGER_NAME = os.environ.get("VD_TRIGGER", default_trigger())
TRIGGER_KEY = getattr(keyboard.Key, TRIGGER_NAME)


recorder = AudioRecorder()
transcriber = None  # set in main()


def start_recording() -> None:
    if recorder.start():
        print("● rec…", flush=True)


def stop_and_transcribe() -> None:
    wav_path, duration = recorder.stop()
    if wav_path is None:
        print("… too short, skipped", flush=True)
        return

    t0 = time.time()
    try:
        text = transcriber.transcribe(wav_path)
    except Exception as e:
        print(f"[error] transcribe: {e}", file=sys.stderr)
        return
    finally:
        Path(wav_path).unlink(missing_ok=True)
    asr_dt = time.time() - t0

    llm_dt = 0.0
    pp_cfg = resolve_postprocess_config()
    if text and pp_cfg is not None:
        t1 = time.time()
        text = lmstudio_cleanup(text, pp_cfg)
        llm_dt = time.time() - t1

    timing = f"{asr_dt:.1f}s ASR"
    if llm_dt:
        timing += f" + {llm_dt:.1f}s LLM"
    print(f"✓ {duration:.1f}s audio → {timing}: {text!r}", flush=True)
    if text:
        paste_text(text)


def on_press(key) -> None:
    if key == TRIGGER_KEY:
        start_recording()


def on_release(key) -> None:
    if key == TRIGGER_KEY:
        threading.Thread(target=stop_and_transcribe, daemon=True).start()


def main() -> None:
    global transcriber
    print(f"Model: {MODEL}  | language: {LANGUAGE}  | trigger: {TRIGGER_NAME}")
    pp_cfg = resolve_postprocess_config()
    if pp_cfg is not None:
        pp_desc = f"on ({pp_cfg['model']} @ {pp_cfg['url']})"
    else:
        pp_desc = "off"
    cfg_source = "runtime config" if CONFIG_PATH.exists() else "env vars"
    print(
        f"initial_prompt: {'on' if PROMPT else 'off'}"
        f"  | postprocess: {pp_desc}  [source: {cfg_source}]"
    )

    transcriber = load_transcriber(MODEL, language=LANGUAGE, initial_prompt=PROMPT)
    print("Warming up model…", flush=True)
    transcriber.warmup()
    print(f"Ready. Hold {TRIGGER_NAME} to talk. Ctrl-C to quit.\n", flush=True)
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
