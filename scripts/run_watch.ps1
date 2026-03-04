# Memory-hub single watcher pass — for OpenClaw heartbeat or Task Scheduler
# Scans ~/Downloads + data/raw/ for new exports, ingests, reconciles, regenerates projections.
#
# Usage:
#   powershell -File scripts\run_watch.ps1
#
# Task Scheduler: trigger every 30 minutes, action = powershell.exe -File <this_script>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogFile = Join-Path $ProjectRoot "reports\watcher_ps.log"

Set-Location (Join-Path $ProjectRoot "memory_hub")

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$timestamp] Starting watcher scan..." | Out-File -Append $LogFile

try {
    & python -m memory_hub.cli watch --once 2>&1 | Out-File -Append $LogFile
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] Scan complete." | Out-File -Append $LogFile
} catch {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] ERROR: $_" | Out-File -Append $LogFile
}
