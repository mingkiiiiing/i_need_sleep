[CmdletBinding()]
param(
    [ValidateRange(5, 1440)]
    [int]$IntervalMinutes = 30,
    [switch]$RunNow,
    [switch]$RunAsSystem
)

$ErrorActionPreference = 'Stop'
$taskName = 'A23-mee-realtime-collect'
$dataCleaningRoot = Split-Path -Parent $PSScriptRoot
$collector = Join-Path $PSScriptRoot 'schedule_mee_collect.bat'
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$userSid = $currentIdentity.User.Value
$logonTypeXml = '<LogonType>InteractiveToken</LogonType>'
$runLevel = 'LeastPrivilege'
if ($RunAsSystem) {
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'RunAsSystem requires an elevated administrator PowerShell session.'
    }
    $userSid = 'S-1-5-18'
    # The Windows Task Scheduler XML schema infers the SYSTEM service-account
    # logon from S-1-5-18; explicitly writing ServiceAccount is rejected.
    $logonTypeXml = ''
    $runLevel = 'HighestAvailable'
}
$start = (Get-Date).AddMinutes($IntervalMinutes).ToString('s')
$taskPathXml = [System.Security.SecurityElement]::Escape($collector)
$workingDirectoryXml = [System.Security.SecurityElement]::Escape($dataCleaningRoot)

# The SYSTEM variant is the production choice: it is passwordless and continues
# when the desktop is locked or the user is signed out.  The current-user option
# remains useful where an elevated installation is not permitted.
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>$userSid</Author><Description>A23 MEE Taihu-basin observed-data collector. Writes immutable raw snapshots and status.</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>$start</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay><Repetition><Interval>PT${IntervalMinutes}M</Interval><Duration>P1D</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>$userSid</UserId>$logonTypeXml<RunLevel>$runLevel</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>Queue</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><ExecutionTimeLimit>PT1H</ExecutionTimeLimit><Priority>7</Priority><WakeToRun>true</WakeToRun>
    <RestartOnFailure><Interval>PT15M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>cmd.exe</Command><Arguments>/d /c &quot;&quot;$taskPathXml&quot;&quot;</Arguments><WorkingDirectory>$workingDirectoryXml</WorkingDirectory></Exec></Actions>
</Task>
"@

Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
$info = Get-ScheduledTaskInfo -TaskName $taskName
if ($RunNow) {
    Start-ScheduledTask -TaskName $taskName
}

[pscustomobject]@{
    task_name = $taskName
    user_sid = $userSid
    interval_minutes = $IntervalMinutes
    run_as_system = [bool]$RunAsSystem
    run_now_requested = [bool]$RunNow
    next_run_time = $info.NextRunTime
    note = if ($RunAsSystem) { 'Runs as SYSTEM, including while the user is signed out; missed runs catch up after resume and failures retry three times.' } else { 'Runs while this user is signed in; missed runs catch up after resume and failures retry three times.' }
} | ConvertTo-Json
