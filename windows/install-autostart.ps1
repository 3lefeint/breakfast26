# Starts Breakfast when the current user logs in (a scheduled task, no admin rights needed).
$ErrorActionPreference = "Stop"
$exe = Join-Path $PSScriptRoot "breakfast.exe"
if (-not (Test-Path $exe)) { throw "breakfast.exe not found next to this script" }
$action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Breakfast" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Starts Breakfast at logon" -Force | Out-Null
Write-Host "Breakfast will start when you log in. Remove it with remove-autostart.ps1."
