param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

$WorkDir = 'D:\Canvas\nudge-agent'
$LogDir = Join-Path $WorkDir 'logs'

$Tasks = @(
    @{ Name = 'CanvasNudgeScan'; Time = '09:00'; Sub = 'scan'; Log = Join-Path $LogDir 'scan.log' },
    @{ Name = 'CanvasNudgePush'; Time = '09:30'; Sub = 'push'; Log = Join-Path $LogDir 'push.log' }
)

foreach ($Task in $Tasks) {
    $Action = "cmd /c cd /d $WorkDir && uv run nudge_agent.py $($Task.Sub) >> $($Task.Log) 2>&1"
    $Command = "schtasks /Create /F /SC DAILY /ST $($Task.Time) /TN $($Task.Name) /TR `"$Action`""

    if ($DryRun) {
        Write-Output $Command
        continue
    }

    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir | Out-Null
    }
    schtasks /Create /F /SC DAILY /ST $Task.Time /TN $Task.Name /TR $Action
}
