$ErrorActionPreference = "Stop"

$backendPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $backendPath ".venv\Scripts\python.exe"
$runnerPath = Join-Path $backendPath "run_ap_scheduled_task.ps1"
if (-not (Test-Path $pythonPath)) {
    throw "Backend virtual environment not found at $pythonPath"
}
if (-not (Test-Path $runnerPath)) {
    throw "Scheduled task runner not found at $runnerPath"
}

$principal = New-ScheduledTaskPrincipal `
    -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew
$startAt = (Get-Date).AddMinutes(1)

function Test-ConfiguredSetting {
    param([string]$Name)

    foreach ($scope in @("Process", "User", "Machine")) {
        if ([Environment]::GetEnvironmentVariable($Name, $scope)) {
            return $true
        }
    }
    return $false
}

$tasks = @(
    @{
        Name = "Templegate AP Approval Notifications"
        Command = "process_approval_notifications"
        Interval = New-TimeSpan -Minutes 60
    }
)

$imapConfigured = (
    (Test-ConfiguredSetting "AP_IMAP_HOST") -and
    (Test-ConfiguredSetting "AP_IMAP_USERNAME") -and
    (Test-ConfiguredSetting "AP_IMAP_PASSWORD")
)
if ($imapConfigured) {
    $tasks += @{
        Name = "Templegate AP IMAP Invoice Import"
        Command = "poll_invoice_mailbox"
        Interval = New-TimeSpan -Minutes 5
    }
}

foreach ($task in $tasks) {
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runnerPath`" -Command $($task.Command)" `
        -WorkingDirectory $backendPath
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At $startAt `
        -RepetitionInterval $task.Interval `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    Register-ScheduledTask `
        -TaskName $task.Name `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Templegate AP workflow automation" `
        -Force | Out-Null
}

Write-Host "Registered hourly approval notification task."
if ($imapConfigured) {
    Write-Host "Registered 5-minute IMAP invoice import task."
} else {
    Write-Host "IMAP settings are missing; mailbox polling was not registered."
}
Write-Host "Tasks run only while this Windows user is signed in."
Write-Host "Re-register the tasks every 10 years to renew their triggers."
