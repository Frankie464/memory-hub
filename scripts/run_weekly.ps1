Set-Location "C:\Users\ogam6\Documents\Code\ChatGPT_Claude"
$timestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
& hub sync --profile weekly 2>&1 | Tee-Object -FilePath "reports\sync_weekly_$timestamp.log"
