# Remove all TRUSTCAST scheduled tasks.
Get-ScheduledTask -TaskPath "\TRUSTCAST\" -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
Write-Output "TRUSTCAST tasks removed"
