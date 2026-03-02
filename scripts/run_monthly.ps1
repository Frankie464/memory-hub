Set-Location "$PSScriptRoot\.."
$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
& hub sync --profile monthly 2>&1 | Tee-Object -FilePath "reports\sync_monthly_$timestamp.log"
