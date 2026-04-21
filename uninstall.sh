#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

LABEL="com.voicedictate.daemon"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "==> unloading LaunchAgent"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true

echo "==> removing plist"
rm -f "$PLIST"

echo "==> removing menu bar .app"
rm -rf menubar/VoiceDictate.app

echo
echo "Done. The .venv and HuggingFace model cache are untouched."
echo "To fully clean up, also remove:"
echo "  $(pwd)/.venv"
echo "  ~/Library/Logs/voice_dictate.log  ~/Library/Logs/voice_dictate.err.log"
echo "  ~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo"
