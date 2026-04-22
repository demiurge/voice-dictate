#!/usr/bin/env pwsh
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

Write-Host "==> unregistering Scheduled Tasks"
Unregister-ScheduledTask -TaskName "VoiceDictateDaemon" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "VoiceDictateTray"   -Confirm:$false -ErrorAction SilentlyContinue

# best-effort kill of any running instances
Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object {
    $_.MainModule.FileName -like "*voice-dictate*"
} | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done. The following are left intact — remove manually to fully clean up:"
Write-Host "  .venv"
Write-Host "  $env:APPDATA\voice-dictate\  (config, presets)"
Write-Host "  $env:LOCALAPPDATA\voice-dictate\  (logs)"
Write-Host "  $env:USERPROFILE\.cache\huggingface\hub\  (downloaded Whisper model)"
