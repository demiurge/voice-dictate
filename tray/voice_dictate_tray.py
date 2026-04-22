#!/usr/bin/env python3
"""VoiceDictate system tray — Windows parallel of the macOS Swift menu bar.

Reads/writes the same config.json + presets.json as the tray on macOS. Polls
recording.flag every 100 ms to flip the icon. Controls the daemon via
schtasks (Start/Stop/Restart) pointed at the VoiceDictateDaemon task.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pystray
from PIL import Image

from core.config import (
    APP_SUPPORT_DIR,
    CONFIG_PATH,
    LOG_DIR,
    PRESETS_PATH,
    redirect_std_to_log,
)
from core.signal import is_recording


redirect_std_to_log()


_ICON_DIR = Path(__file__).parent
_ICON_IDLE = Image.open(_ICON_DIR / "mic.png")
_ICON_REC = Image.open(_ICON_DIR / "mic_rec.png")

DAEMON_TASK = "VoiceDictateDaemon"

_models_cache: dict[str, tuple[float, list[str]]] = {}
_MODELS_TTL = 120.0


def _load_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"postprocess": False, "active_preset": "", "current_model": ""}


def _save_config(cfg: dict[str, Any]) -> None:
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8"
    )


def _load_presets() -> list[dict[str, Any]]:
    try:
        return json.loads(PRESETS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []


def _fetch_models(base_url: str) -> list[str]:
    now = time.time()
    cached = _models_cache.get(base_url)
    if cached and now - cached[0] < _MODELS_TTL:
        return cached[1]
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            data = json.loads(resp.read())
        models = sorted(m["id"] for m in data.get("data", []))
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
        models = []
    _models_cache[base_url] = (now, models)
    return models


def _daemon_status() -> str:
    try:
        out = subprocess.run(
            ["schtasks", "/Query", "/TN", DAEMON_TASK, "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        parts = out.stdout.strip().split(",")
        status = parts[-1].strip().strip('"') if parts else "?"
        return f"Status: {status}"
    except (subprocess.SubprocessError, FileNotFoundError):
        return "Status: ?"


def _checker(key: str, value: str) -> Callable[[pystray.MenuItem], bool]:
    return lambda it: _load_config().get(key) == value


def _pp_checker() -> Callable[[pystray.MenuItem], bool]:
    return lambda it: bool(_load_config().get("postprocess"))


class VDTray:
    def __init__(self) -> None:
        self.icon = pystray.Icon(
            "voice-dictate",
            _ICON_IDLE,
            "VoiceDictate",
            menu=self._build_menu(),
        )
        self._last_rec = False

    def _build_menu(self) -> pystray.Menu:
        cfg = _load_config()
        presets = _load_presets()
        active_id = cfg.get("active_preset", "")
        active = next((p for p in presets if p.get("id") == active_id), None)
        current_model = cfg.get("current_model") or ""

        if presets:
            preset_items = [
                pystray.MenuItem(
                    p.get("name", "(unnamed)"),
                    self._make_select_preset(p.get("id", "")),
                    checked=_checker("active_preset", p.get("id", "")),
                    radio=True,
                )
                for p in presets
            ]
        else:
            preset_items = [pystray.MenuItem("(no presets)", None, enabled=False)]

        if not active or not active.get("base_url"):
            model_items = [
                pystray.MenuItem("(no active preset)", None, enabled=False)
            ]
        else:
            models = _fetch_models(active["base_url"])
            if not models:
                model_items = [
                    pystray.MenuItem("(endpoint offline)", None, enabled=False)
                ]
            else:
                model_items = [
                    pystray.MenuItem(
                        m,
                        self._make_select_model(m),
                        checked=_checker("current_model", m),
                        radio=True,
                    )
                    for m in models
                ]

        preset_title = (
            f"Preset: {active['name']}" if active else "Preset: (none)"
        )
        model_title = f"Model: {current_model or '(none)'}"

        return pystray.Menu(
            pystray.MenuItem(_daemon_status(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Post-processing", self._on_toggle_postprocess, checked=_pp_checker()
            ),
            pystray.MenuItem(preset_title, pystray.Menu(*preset_items)),
            pystray.MenuItem(model_title, pystray.Menu(*model_items)),
            pystray.MenuItem("Edit Presets…", self._on_edit_presets),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start", self._on_start),
            pystray.MenuItem("Stop", self._on_stop),
            pystray.MenuItem("Restart", self._on_restart),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Log", self._on_show_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

    def _rebuild(self) -> None:
        self.icon.menu = self._build_menu()
        self.icon.update_menu()

    # --- actions ---
    def _on_toggle_postprocess(self, icon, item) -> None:
        cfg = _load_config()
        cfg["postprocess"] = not bool(cfg.get("postprocess"))
        if not cfg.get("active_preset"):
            presets = _load_presets()
            if presets:
                cfg["active_preset"] = presets[0].get("id", "")
        _save_config(cfg)
        self._rebuild()

    def _make_select_preset(self, preset_id: str) -> Callable:
        def action(icon, item) -> None:
            cfg = _load_config()
            cfg["active_preset"] = preset_id
            preset = next(
                (p for p in _load_presets() if p.get("id") == preset_id), None
            )
            if preset and preset.get("default_model"):
                cfg["current_model"] = preset["default_model"]
            else:
                cfg["current_model"] = ""
            _save_config(cfg)
            self._rebuild()

        return action

    def _make_select_model(self, model: str) -> Callable:
        def action(icon, item) -> None:
            cfg = _load_config()
            cfg["current_model"] = model
            _save_config(cfg)
            self._rebuild()

        return action

    def _on_edit_presets(self, icon, item) -> None:
        APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        if not PRESETS_PATH.exists():
            PRESETS_PATH.write_text("[]\n", encoding="utf-8")
        os.startfile(str(PRESETS_PATH))

    def _on_show_log(self, icon, item) -> None:
        log = LOG_DIR / "voice_dictate.log"
        if log.exists():
            os.startfile(str(log))

    def _schtasks(self, verb: str) -> None:
        try:
            subprocess.run(
                ["schtasks", verb, "/TN", DAEMON_TASK],
                capture_output=True,
                timeout=5,
            )
        except subprocess.SubprocessError:
            pass

    def _on_start(self, icon, item) -> None:
        self._schtasks("/Run")

    def _on_stop(self, icon, item) -> None:
        self._schtasks("/End")

    def _on_restart(self, icon, item) -> None:
        self._schtasks("/End")
        time.sleep(0.3)
        self._schtasks("/Run")

    def _on_quit(self, icon, item) -> None:
        self.icon.stop()

    # --- recording-flag poll loop ---
    def _poll_loop(self) -> None:
        while True:
            rec = is_recording()
            if rec != self._last_rec:
                try:
                    self.icon.icon = _ICON_REC if rec else _ICON_IDLE
                except Exception:
                    pass  # pystray icon assign is not formally thread-safe
                self._last_rec = rec
            time.sleep(0.1)

    def run(self) -> None:
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self.icon.run()


def main() -> None:
    VDTray().run()


if __name__ == "__main__":
    main()
