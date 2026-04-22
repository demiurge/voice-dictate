#!/usr/bin/env pwsh
# Installs voice-dictate on Windows: venv + deps + Task Scheduler + tray.
# Requires Windows 10/11 x64, Python 3.10+ from python.org, NVIDIA GPU.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Root = $PWD.Path

Write-Host "==> preflight"

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw "python not found. Install from python.org (NOT Microsoft Store)."
}
if ($python -match "\\WindowsApps\\") {
    throw "Microsoft Store Python alias detected at $python. Install real Python from python.org and re-run."
}
$pyVer = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pyVer -lt [version]"3.10") {
    throw "Need Python 3.10+, got $pyVer"
}
$pyArch = & $python -c "import platform; print(platform.machine())"
if ($pyArch -ne "AMD64") {
    throw "Need x64 Python, got $pyArch"
}
Write-Host "    Python: $python (v$pyVer, $pyArch)"

$nvidia = Get-CimInstance Win32_VideoController | Where-Object Name -match "NVIDIA"
if (-not $nvidia) {
    Write-Warning "No NVIDIA GPU detected. CUDA backend will fail at runtime."
} else {
    Write-Host "    GPU: $($nvidia.Name | Select-Object -First 1)"
}

Write-Host "==> creating venv"
if (-not (Test-Path .venv)) { & $python -m venv .venv }

Write-Host "==> installing Python dependencies (faster-whisper + CUDA wheels; ~2 GB)"
& .venv\Scripts\pip.exe install -q --upgrade pip
& .venv\Scripts\pip.exe install -q -r requirements-win.txt

Write-Host "==> smoke-testing CUDA + faster-whisper"
& .venv\Scripts\python.exe -c @"
import os, nvidia.cublas, nvidia.cudnn
for p in (nvidia.cublas, nvidia.cudnn):
    bin_dir = os.path.join(p.__path__[0], 'bin')
    os.add_dll_directory(bin_dir)
    os.environ['PATH'] = bin_dir + os.pathsep + os.environ.get('PATH', '')
from faster_whisper import WhisperModel
# Actually run encode() — CT2 spawns worker child processes that need PATH,
# not just add_dll_directory. The import-only test would miss this.
import tempfile, numpy as np, soundfile as sf
with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as t:
    sf.write(t.name, np.zeros(8000, dtype=np.float32), 16000)
    wav = t.name
try:
    m = WhisperModel('tiny', device='cuda', compute_type='float16')
    list(m.transcribe(wav, language='en')[0])
finally:
    os.unlink(wav)
print('ctranslate2 + CUDA OK')
"@
if ($LASTEXITCODE -ne 0) {
    throw "CUDA wheels failed to load. Check NVIDIA driver (need >= 525)."
}

Write-Host "==> provisioning runtime config"
$appData = "$env:APPDATA\voice-dictate"
$logDir  = "$env:LOCALAPPDATA\voice-dictate\logs"
New-Item -ItemType Directory -Force -Path $appData, $logDir | Out-Null
if (-not (Test-Path "$appData\presets.json")) {
    Copy-Item "$Root\config\presets.default.json" "$appData\presets.json"
    Write-Host "    installed default presets.json"
} else {
    Write-Host "    presets.json already present — leaving user edits intact"
}
if (-not (Test-Path "$appData\config.json")) {
    $cfg = @{
        active_preset = "gemma4-e4b-lmstudio"
        current_model = "gemma-4-e4b-it"
        postprocess = $false
    } | ConvertTo-Json
    # UTF-8 without BOM — PowerShell 5.1's Set-Content -Encoding UTF8 adds a
    # BOM that trips Python's json.loads("﻿{..."). Write the raw bytes
    # with a BOM-less encoder instead.
    [System.IO.File]::WriteAllText("$appData\config.json", $cfg, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "    installed default config.json (post-processing off)"
} else {
    Write-Host "    config.json already present — leaving user state intact"
}

Write-Host "==> registering Scheduled Tasks"
$user = "$env:USERDOMAIN\$env:USERNAME"
$pythonw = "$Root\.venv\Scripts\pythonw.exe"

function Register-VDTask($taskName, $templatePath, $scriptPath) {
    $xml = (Get-Content $templatePath -Raw) `
        -replace "__USER__",    $user `
        -replace "__PYTHONW__", $pythonw `
        -replace "__SCRIPT__",  $scriptPath `
        -replace "__WORKDIR__", $Root
    Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Host "    registered $taskName"
}

Register-VDTask "VoiceDictateDaemon" "$Root\scheduled_tasks\daemon.xml.template" "$Root\voice_dictate.py"
Register-VDTask "VoiceDictateTray"   "$Root\scheduled_tasks\tray.xml.template"   "$Root\tray\voice_dictate_tray.py"

Write-Host "==> detecting local LLM endpoints (optional)"
try {
    $r = Invoke-WebRequest http://localhost:1234/v1/models -TimeoutSec 1 -UseBasicParsing
    $count = (($r.Content | ConvertFrom-Json).data).Count
    Write-Host "    [OK] LM Studio online at localhost:1234 ($count models)"
} catch {
    try {
        Invoke-WebRequest http://localhost:11434/v1/models -TimeoutSec 1 -UseBasicParsing | Out-Null
        Write-Host "    [OK] Ollama online at localhost:11434"
    } catch {
        Write-Host "    [--] No local LLM detected"
    }
}

Write-Host ""
Write-Host "=============================================================="
Write-Host "  Installation complete."
Write-Host ""
Write-Host "  Hold RIGHT CTRL and speak. Release -> text is pasted into"
Write-Host "  the focused window."
Write-Host ""
Write-Host "  Config:  $appData\"
Write-Host "  Logs:    $logDir\"
Write-Host "  Uninstall:  .\uninstall.ps1"
Write-Host "=============================================================="
