param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("process_approval_notifications", "poll_invoice_mailbox")]
    [string]$Command
)

$ErrorActionPreference = "Stop"
$backendPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $backendPath ".venv\Scripts\python.exe"
$managePath = Join-Path $backendPath "manage.py"
$logDirectory = Join-Path $backendPath "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory "$Command.log"

& $pythonPath $managePath $Command *>> $logPath
if ($LASTEXITCODE -ne 0) {
    Add-Content -Path $logPath -Value "Command failed with exit code $LASTEXITCODE at $(Get-Date -Format o)"
    exit $LASTEXITCODE
}
