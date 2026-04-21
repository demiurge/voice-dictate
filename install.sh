#!/usr/bin/env bash
# Installs voice-dictate: venv + deps + LaunchAgent + menu bar .app.
# Requires macOS 12+, Apple Silicon recommended, Python 3.10+.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

LABEL="com.voicedictate.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"
APP_SUPPORT="$HOME/Library/Application Support/voice-dictate"

# --- preflight: Apple Silicon only -------------------------------------------
HOST_ARCH="$(uname -m)"
if [[ "$HOST_ARCH" != "arm64" ]]; then
    echo "error: MLX requires Apple Silicon (arm64). Detected: $HOST_ARCH"
    echo "       This package will not work on Intel Macs."
    exit 1
fi

command -v swiftc >/dev/null || { echo "error: swiftc not found — install Xcode Command Line Tools: xcode-select --install"; exit 1; }

PYTHON="${PYTHON:-$(command -v python3.12 || command -v python3.11 || command -v python3 || true)}"
[[ -n "$PYTHON" ]] || { echo "error: python3 not found — install from python.org or: brew install python@3.12"; exit 1; }

PY_ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
if [[ "$PY_ARCH" != "arm64" ]]; then
    echo "error: your Python is $PY_ARCH (likely running under Rosetta)."
    echo "       MLX needs a native arm64 Python. Install one with:"
    echo "         brew install python@3.12"
    echo "       Or pass an explicit interpreter: PYTHON=/opt/homebrew/bin/python3.12 ./install.sh"
    exit 1
fi
echo "Using Python: $PYTHON ($PY_ARCH)"

echo "==> creating venv"
[[ -d .venv ]] || "$PYTHON" -m venv .venv

echo "==> installing Python dependencies (mlx, mlx-metal, mlx-whisper pull in ~1 GB)"
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

# sanity check: MLX actually loads on this machine
./.venv/bin/python -c "import mlx.core as mx; a = mx.array([1.0]); assert (a + 1).item() == 2.0" \
    || { echo "error: mlx import/runtime test failed"; exit 1; }

echo "==> provisioning runtime config"
mkdir -p "$APP_SUPPORT"
if [[ ! -f "$APP_SUPPORT/presets.json" ]]; then
    cp "$ROOT/config/presets.default.json" "$APP_SUPPORT/presets.json"
    echo "    installed default presets.json (Bielik / LM Studio / Ollama)"
else
    echo "    presets.json already present — leaving user edits intact"
fi
if [[ ! -f "$APP_SUPPORT/config.json" ]]; then
    cat > "$APP_SUPPORT/config.json" <<'JSON'
{
  "active_preset": "bielik-lmstudio",
  "current_model": "bielik-11b-v3.0-instruct-mlx",
  "postprocess": false
}
JSON
    echo "    installed default config.json (post-processing off by default)"
else
    echo "    config.json already present — leaving user state intact"
fi

echo "==> generating LaunchAgent plist"
mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
sed \
    -e "s|__PYTHON__|$ROOT/.venv/bin/python|g" \
    -e "s|__SCRIPT__|$ROOT/voice_dictate.py|g" \
    -e "s|__WORKDIR__|$ROOT|g" \
    -e "s|__LABEL__|$LABEL|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    launchd/com.voicedictate.daemon.plist.template > "$PLIST"

echo "==> building menu bar .app"
( cd menubar && ./build.sh )

echo "==> loading LaunchAgent"
# Unload any existing instance and wait for it to actually be gone. `bootout`
# is asynchronous — calling `bootstrap` immediately after often fails with
# "Bootstrap failed: 5: Input/output error".
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
    launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 || break
    sleep 0.5
done
pkill -f voice_dictate.py 2>/dev/null || true

launchctl bootstrap "gui/$UID" "$PLIST"
launchctl enable "gui/$UID/$LABEL"

VENV_PY="$ROOT/.venv/bin/python"

# Put the path on the clipboard so it's ready for ⌘V in the file picker.
printf "%s" "$VENV_PY" | pbcopy 2>/dev/null || true

echo "==> launching menu bar app"
pkill -x VoiceDictate 2>/dev/null || true
sleep 0.5
open "$ROOT/menubar/VoiceDictate.app" 2>/dev/null || true

echo "==> detecting local LLM endpoints (optional, for post-processing)"
LLM_STATUS=""
if curl -s --max-time 1 http://localhost:1234/v1/models >/dev/null 2>&1; then
    N=$(curl -s --max-time 2 http://localhost:1234/v1/models \
        | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('data', [])))" 2>/dev/null || echo "?")
    LLM_STATUS="    ✓ LM Studio online at localhost:1234 ($N models)"
elif curl -s --max-time 1 http://localhost:11434/v1/models >/dev/null 2>&1; then
    LLM_STATUS="    ✓ Ollama online at localhost:11434"
else
    LLM_STATUS="    ℹ  No local LLM detected (install LM Studio or Ollama to enable post-processing)"
fi
echo "$LLM_STATUS"

cat <<EOF

╔══════════════════════════════════════════════════════════════════════════╗
║   ACTION REQUIRED — without this, auto-paste (⌘V) will NOT work          ║
╚══════════════════════════════════════════════════════════════════════════╝

 1. In the Accessibility panel that is about to open:
      • click [ + ], press ⌘⇧G, paste the path below (⌘V), click Open
      • make sure the toggle next to "python" is ON

    Path (already on your clipboard):

        $VENV_PY

 2. Kickstart the daemon so it re-checks permissions:

        launchctl kickstart -k gui/\$UID/$LABEL

 3. On first recording, allow Microphone access when macOS asks.


Optional — LLM post-processing (OFF by default)
───────────────────────────────────────────────

 • The daemon now transcribes with Whisper only. To also get punctuation,
   filler-word removal and phonetic ASR-error repair, run a local LLM:
     - LM Studio (https://lmstudio.ai)  — load Bielik 11B for Polish
     - or Ollama (https://ollama.com)   — any OpenAI-compatible server works
 • Start the server, then click the mic icon in your menu bar:
     Post-processing (toggle)  →  Preset ▸  →  Model ▸
   Changes take effect on the next dictation — no daemon restart needed.
 • To add your own endpoint: menu bar → Edit Presets…


Auto-start on login
───────────────────

 • The daemon (voice recognition) already auto-starts via LaunchAgent.
 • The menu bar app was just launched. To have it start automatically too:
   System Settings → General → Login Items → [ + ] → choose
       $ROOT/menubar/VoiceDictate.app


 Logs     : $LOG_DIR/voice_dictate.log   $LOG_DIR/voice_dictate.err.log
 Config   : $APP_SUPPORT/ (config.json, presets.json — managed by menu bar)
 Uninstall: ./uninstall.sh

EOF

# Open the right System Settings pane directly.
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
