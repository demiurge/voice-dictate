"""Local LLM post-processing pipeline (OpenAI-compatible /v1/chat/completions).

Resolution order for whether post-processing is on and which endpoint/model
to use:
  1. Runtime config files (~/Library/Application Support/voice-dictate/...
     or %APPDATA%\\voice-dictate\\...), written by the tray app.
  2. Legacy env vars (VD_POSTPROCESS=lmstudio + VD_LMSTUDIO_*).
  3. None -> post-processing disabled.

On any LLM failure (endpoint off, timeout, bad response), lmstudio_cleanup
returns the original text so dictation keeps working.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from core.config import CONFIG_PATH, PRESETS_PATH


POSTPROCESS = os.environ.get("VD_POSTPROCESS", "").lower()
LMSTUDIO_URL = os.environ.get(
    "VD_LMSTUDIO_URL", "http://localhost:1234/v1/chat/completions"
)
LMSTUDIO_MODEL = os.environ.get("VD_LMSTUDIO_MODEL", "bielik")

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


def resolve_postprocess_config() -> dict | None:
    """Return {'url', 'model', 'system_prompt'} or None if disabled."""
    try:
        if CONFIG_PATH.exists() and PRESETS_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if not cfg.get("postprocess"):
                return None
            presets = json.loads(PRESETS_PATH.read_text(encoding="utf-8-sig"))
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
        print(
            f"[warn] runtime config unreadable, falling back to env: {e}",
            file=sys.stderr,
        )

    if POSTPROCESS == "lmstudio":
        return {
            "url": LMSTUDIO_URL,
            "model": LMSTUDIO_MODEL,
            "system_prompt": LMSTUDIO_SYSTEM,
        }
    return None


def lmstudio_cleanup(text: str, cfg: dict, timeout: float = 8.0) -> str:
    """Send transcript through an OpenAI-compatible local LLM.

    Falls back to the original text on any failure so dictation keeps working.
    """
    payload = json.dumps(
        {
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": cfg["system_prompt"]},
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "max_tokens": 512,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        cfg["url"], data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        cleaned = data["choices"][0]["message"]["content"].strip()
        return cleaned or text
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        print(f"[warn] postprocess failed, keeping raw text: {e}", file=sys.stderr)
        return text
