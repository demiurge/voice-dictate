# voice-dictate

Push-to-talk voice dictation for macOS using **MLX Whisper** running fully
locally on Apple Silicon. Hold a trigger key to record, release to transcribe
and auto-paste into the active window. No cloud, no API keys.

- 🎙️ ~0.3–1 s ASR latency for a 10 s utterance on an M-series Mac
- 🇵🇱 Built and tuned for Polish, works with any Whisper-supported language
- 🍎 Ships with a tiny Swift menu bar app (Pause/Resume/Restart + live recording indicator)
- 🔁 Runs as a LaunchAgent, auto-starts on login
- 🔒 100% local — model + audio never leave your machine

## Szybki start (PL)

```bash
git clone https://github.com/demiurge/voice-dictate.git
cd voice-dictate
./install.sh
```

Dodaj `./.venv/bin/python` do **System Settings → Privacy & Security → Accessibility**, a potem:

```bash
launchctl kickstart -k gui/$UID/com.voicedictate.daemon
```

Trzymaj **prawy ⌥** i mów. Po puszczeniu tekst wklei się w aktywne okno.

## Requirements

- macOS 12 or newer
- **Apple Silicon (M1/M2/M3/M4) — MLX does not support Intel Macs.** `install.sh` verifies the host architecture and aborts otherwise.
- Xcode Command Line Tools (`xcode-select --install`) — for `swiftc`
- **A native arm64 Python 3.10+**. A Python running under Rosetta (`x86_64`) will pick up incompatible wheels and MLX will fail at import. The easiest path is Homebrew on Apple Silicon:
  ```
  brew install python@3.12
  ```
  `install.sh` verifies `platform.machine() == 'arm64'` before continuing.
- Microphone

The first run downloads the Whisper model (~1.5 GB for `large-v3-turbo`) to
`~/.cache/huggingface/hub`. `mlx`, `mlx-metal` and `mlx-whisper` together are
roughly another 1 GB inside the venv.

## Install

```bash
./install.sh
```

This will:

1. Create `.venv/` and install Python deps from `requirements.txt`.
2. Generate `~/Library/LaunchAgents/com.voicedictate.daemon.plist` with paths
   substituted for your machine.
3. Build `menubar/VoiceDictate.app` with `swiftc`.
4. Load the LaunchAgent (starts the daemon immediately and on every login).

### Grant permissions

macOS TCC keeps **Accessibility** and **Input Monitoring** as separate
permission scopes. The daemon needs **Accessibility** specifically — Input
Monitoring is not enough, because `⌘V` is *sent*, not just *received*.

1. **Accessibility** (required for auto-paste)
   - System Settings → Privacy & Security → **Accessibility** → `+`
   - ⌘⇧G, paste the absolute path to `.venv/bin/python`, enable the toggle.
2. **Microphone** — the first recording will prompt; allow it.

After granting Accessibility, restart the daemon so it re-checks trust:

```bash
launchctl kickstart -k gui/$UID/com.voicedictate.daemon
```

Verify that `This process is not trusted!` is **no longer** appearing for the
current PID in `~/Library/Logs/voice_dictate.err.log`.

## Usage

- **Hold right Option (⌥)** → recording starts (ikon in the menu bar turns into a filled red mic).
- **Release** → Whisper transcribes → text is placed on the clipboard and pasted into the focused app with `⌘V`.
- Utterances shorter than 300 ms are ignored.

### Menu bar app

Open `menubar/VoiceDictate.app` (or `open menubar/VoiceDictate.app` from this
directory). It gives you:

- Live status (Running / Stopped, PID)
- Pause · Resume · Restart (wrap `launchctl bootout/bootstrap/kickstart`)
- Show Log (opens `~/Library/Logs/voice_dictate.log`)
- Red filled mic icon while recording (tails the log for the `● rec…` marker)

To auto-start the menu bar app at login: System Settings → General → Login
Items → `+` and pick `VoiceDictate.app`.

## Configuration

Override defaults via environment variables in the LaunchAgent plist (add an
entry under `EnvironmentVariables`):

| Variable      | Default                                     | Notes                                                                 |
|---------------|---------------------------------------------|-----------------------------------------------------------------------|
| `VD_MODEL`    | `mlx-community/whisper-large-v3-turbo`      | Any MLX Whisper HF repo or local path. `large-v3` is slower but ~1 pp more accurate on PL. |
| `VD_LANGUAGE` | `pl`                                        | 2-letter code passed to Whisper.                                      |
| `VD_TRIGGER`  | `alt_r`                                     | A name from [`pynput.keyboard.Key`](https://pynput.readthedocs.io/en/latest/keyboard.html#pynput.keyboard.Key), e.g. `f13`, `ctrl_r`. |

After changing the plist:

```bash
launchctl kickstart -k gui/$UID/com.voicedictate.daemon
```

## Useful commands

```bash
# status
launchctl list | grep voicedictate

# restart
launchctl kickstart -k gui/$UID/com.voicedictate.daemon

# stop
launchctl bootout gui/$UID/com.voicedictate.daemon

# start
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.voicedictate.daemon.plist

# tail logs
tail -F ~/Library/Logs/voice_dictate.log
tail -F ~/Library/Logs/voice_dictate.err.log
```

## Uninstall

```bash
./uninstall.sh
```

Removes the LaunchAgent, the plist, and the menu bar `.app`. Leaves the `.venv`
and the downloaded Whisper model in place (see the script for the commands to
fully clean up).

## Security notes

The package is **local-only** — audio, transcripts, and the model never leave
your machine. That said, any hotkey-driven dictation tool on macOS
necessarily takes on broad privileges. Read this section before you grant
Accessibility.

- **Transcript log is plaintext and unbounded.** Every utterance is written
  to `~/Library/Logs/voice_dictate.log` by the LaunchAgent, including
  anything sensitive you happen to dictate. The file stays until you delete
  it and is readable by any process running as you. To opt out, point
  `StandardOutPath` in the plist at `/dev/null`, or remove the transcript
  from the `print(...)` calls in `voice_dictate.py`.

- **Accessibility is a broad permission.** What lets the daemon send `⌘V`
  also lets anything running inside the same Python process send arbitrary
  keystrokes to any focused app — Terminal, `sudo` prompts, 1Password, a
  bank site. A compromised dependency inherits that power. Review the venv
  before granting access; consider pinning versions.

- **The listener sees every keystroke.** `pynput` installs a global event
  tap to detect the trigger. Our code only reacts to right Option, but a
  compromised interpreter could observe every key press.

- **The clipboard holds the last transcript.** Any app with Pasteboard
  access can read it after the ⌘V fires. If you dictate something
  sensitive, clear it with `pbcopy < /dev/null`.

- **Auto-paste goes to the focused window.** If focus is not where you
  expect (Slack instead of Claude Code), your dictation lands in the wrong
  app. There is no undo once the keystrokes are delivered.

- **Unpinned dependencies.** `requirements.txt` uses `>=` to stay current.
  For reproducible installs, run `./.venv/bin/pip freeze > requirements.lock`
  after a known-good `install.sh` and distribute the lock file alongside
  the repo.

- **Binaries are not code-signed.** `menubar/VoiceDictate.app` is built
  locally with `swiftc` and carries no Developer ID or notarization.
  Gatekeeper will ask to confirm the first launch. For wider distribution
  you would need an Apple developer account plus `codesign` and
  `notarytool`.

- **Supply chain.** You are trusting PyPI for the Python packages and
  HuggingFace for the Whisper weights
  (`mlx-community/whisper-large-v3-turbo`). These are standard but
  unaudited by this project.

## Troubleshooting

### Recording works but nothing gets pasted

The daemon can listen for the trigger key without Accessibility (session-level
event tap), but cannot **send** `⌘V` without it. Check
`~/Library/Logs/voice_dictate.err.log` — if you see `This process is not
trusted!` for the current PID, Accessibility is not granted yet.

Fix:

1. Make sure you added the python binary to **Accessibility**, not only to
   **Input Monitoring** — these are two different panels in System Settings.
2. If the entry is already there, toggle it off and on again (forces TCC
   refresh).
3. `launchctl kickstart -k gui/$UID/com.voicedictate.daemon`

### Double-paste

You probably have two instances running (e.g. one manual, one from the
LaunchAgent). Check:

```bash
pgrep -af voice_dictate.py
```

Kill stray processes.

### `swiftc: command not found`

Install Xcode Command Line Tools: `xcode-select --install`.

### `mlx` import fails / segfault on startup

Almost always means Python is running under Rosetta (`x86_64`). Check with:

```bash
./.venv/bin/python -c "import platform; print(platform.machine())"
```

Expected: `arm64`. If you see `x86_64`, install a native Python (`brew install
python@3.12`) and re-run `./install.sh` — the installer will also delete and
recreate the venv if you `rm -rf .venv` first.

### First transcription is slow

MLX compiles kernels on first run. `install.sh` warms the model up during
startup, but the very first *real* call after a model change takes an extra
few seconds.

## How it works

```
hotkey press  ──►  sounddevice InputStream (16 kHz mono f32)
                       │
hotkey release ──►  stop stream, dump to WAV
                       │
                 mlx_whisper.transcribe(model=turbo, language=pl)
                       │
                 pyperclip.copy(text)
                       │
                 pynput.Controller.press(⌘V)  ──►  active window
```

The LaunchAgent just keeps the Python process alive; the menu bar app is a
pure remote control on top of `launchctl` plus a `tail -F` on the log file
for the recording indicator.

## License

MIT. See [LICENSE](LICENSE).
