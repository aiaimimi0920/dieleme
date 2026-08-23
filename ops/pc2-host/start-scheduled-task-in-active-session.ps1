param(
  [Parameter(Mandatory = $true)][string]$TaskName,
  [string]$TaskPath = '\',
  [int]$TimeoutSeconds = 30,
  [switch]$Supervise
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not ('FapaiPc2.ActiveSessionProcess' -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace FapaiPc2 {
  public static class ActiveSessionProcess {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct STARTUPINFO {
      public int cb;
      public string lpReserved;
      public string lpDesktop;
      public string lpTitle;
      public int dwX;
      public int dwY;
      public int dwXSize;
      public int dwYSize;
      public int dwXCountChars;
      public int dwYCountChars;
      public int dwFillAttribute;
      public int dwFlags;
      public short wShowWindow;
      public short cbReserved2;
      public IntPtr lpReserved2;
      public IntPtr hStdInput;
      public IntPtr hStdOutput;
      public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_INFORMATION {
      public IntPtr hProcess;
      public IntPtr hThread;
      public int dwProcessId;
      public int dwThreadId;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint WTSGetActiveConsoleSessionId();

    [DllImport("wtsapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool WTSQueryUserToken(uint sessionId, out IntPtr tokenHandle);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr OpenProcess(uint access, bool inheritHandle, int processId);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool OpenProcessToken(
      IntPtr processHandle,
      uint desiredAccess,
      out IntPtr tokenHandle
    );

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DuplicateTokenEx(
      IntPtr existingToken,
      uint desiredAccess,
      IntPtr tokenAttributes,
      int impersonationLevel,
      int tokenType,
      out IntPtr newToken
    );

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CreateProcessWithTokenW(
      IntPtr token,
      uint logonFlags,
      string applicationName,
      StringBuilder commandLine,
      uint creationFlags,
      IntPtr environment,
      string currentDirectory,
      ref STARTUPINFO startupInfo,
      out PROCESS_INFORMATION processInformation
    );

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CreateProcessAsUserW(
      IntPtr token,
      string applicationName,
      StringBuilder commandLine,
      IntPtr processAttributes,
      IntPtr threadAttributes,
      bool inheritHandles,
      uint creationFlags,
      IntPtr environment,
      string currentDirectory,
      ref STARTUPINFO startupInfo,
      out PROCESS_INFORMATION processInformation
    );

    [DllImport("userenv.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CreateEnvironmentBlock(
      out IntPtr environment,
      IntPtr token,
      bool inherit
    );

    [DllImport("userenv.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DestroyEnvironmentBlock(IntPtr environment);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr handle);
  }
}
'@
}

function Assert-Win32Result {
  param(
    [Parameter(Mandatory = $true)][bool]$Succeeded,
    [Parameter(Mandatory = $true)][string]$Operation
  )

  if (-not $Succeeded) {
    $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    throw "$Operation failed with Win32 error $code"
  }
}

$bootstrapLogPath = 'C:\fapaifang-worker\logs\codex-pc2-real\cdp-self-heal-bootstrap.log'
function Write-BootstrapLog {
  param(
    [Parameter(Mandatory = $true)][string]$Event,
    [hashtable]$Details = @{}
  )

  $payload = [ordered]@{ ts = (Get-Date).ToString('s'); event = $Event }
  foreach ($key in $Details.Keys) { $payload[$key] = $Details[$key] }
  Add-Content -LiteralPath $bootstrapLogPath -Value ($payload | ConvertTo-Json -Compress -Depth 4) -Encoding UTF8
}

function Get-WatchdogLatestActivity {
  $latest = [datetime]::MinValue
  foreach ($path in @(
    'C:\fapaifang-worker\state\cdp-self-heal-state.json',
    'C:\fapaifang-worker\logs\codex-pc2-real\cdp-self-heal.log'
  )) {
    $item = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    if ($null -ne $item -and $item.LastWriteTime -gt $latest) {
      $latest = $item.LastWriteTime
    }
  }
  return $latest
}

function Wait-WatchdogProcess {
  param(
    [Parameter(Mandatory = $true)][int]$ProcessId,
    [int]$StartupGraceSeconds = 90,
    [int]$MaxSilenceSeconds = 300
  )

  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($null -eq $process) {
    throw "PC2 CDP self-heal process $ProcessId exited"
  }
  $startedAt = $process.StartTime
  while ($null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
    $now = Get-Date
    $latestActivity = Get-WatchdogLatestActivity
    $activityBelongsToProcess = $latestActivity -ge $startedAt.AddSeconds(-5)
    $startupGraceElapsed = ($now - $startedAt).TotalSeconds -ge $StartupGraceSeconds
    $activityStale = $latestActivity -eq [datetime]::MinValue -or `
      ($now - $latestActivity).TotalSeconds -ge $MaxSilenceSeconds
    if ($startupGraceElapsed -and (-not $activityBelongsToProcess -or $activityStale)) {
      Write-BootstrapLog -Event 'watchdog_unresponsive' -Details @{
        process_id = $ProcessId
        started_at = $startedAt.ToString('s')
        latest_activity = if ($latestActivity -eq [datetime]::MinValue) { '' } else { $latestActivity.ToString('s') }
        max_silence_seconds = $MaxSilenceSeconds
      }
      & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
      Start-Sleep -Seconds 2
      throw "PC2 CDP self-heal process $ProcessId stopped producing health activity"
    }
    Start-Sleep -Seconds 15
  }
  throw "PC2 CDP self-heal process $ProcessId exited"
}

function Get-TaskActionDefinition {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Path
  )

  $service = $null
  $folder = $null
  $registeredTask = $null
  $actions = $null
  $action = $null
  try {
    # ScheduledTasks cmdlets use CIM and can block for minutes on PC2. The
    # native Task Scheduler COM API reads the same registered action directly.
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder($Path)
    $registeredTask = $folder.GetTask($Name)
    $actions = $registeredTask.Definition.Actions
    if ($actions.Count -lt 1) {
      throw "Scheduled task $Path$Name has no action"
    }
    $action = $actions.Item(1)
    return [pscustomobject]@{
      execute = [string]$action.Path
      arguments = [string]$action.Arguments
      working_directory = [string]$action.WorkingDirectory
    }
  } finally {
    foreach ($comObject in @($action, $actions, $registeredTask, $folder, $service)) {
      if ($null -ne $comObject -and [Runtime.InteropServices.Marshal]::IsComObject($comObject)) {
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($comObject)
      }
    }
  }
}
trap {
  Write-BootstrapLog -Event 'bootstrap_failed' -Details @{ error = $_.Exception.Message }
  exit 1
}

$activeSessionId = [FapaiPc2.ActiveSessionProcess]::WTSGetActiveConsoleSessionId()
if ($activeSessionId -eq [uint32]::MaxValue) {
  throw 'No active console session is available'
}
$explorer = @(
  Get-Process -Name explorer -ErrorAction SilentlyContinue |
    Where-Object { $_.SessionId -eq [int]$activeSessionId } |
    Sort-Object StartTime
) | Select-Object -First 1
if ($null -eq $explorer) {
  throw "No explorer.exe process is available in active console session $activeSessionId"
}
Write-BootstrapLog -Event 'bootstrap_started' -Details @{ active_session_id = [int]$activeSessionId; supervise = [bool]$Supervise }

$existingSelfHeal = @(
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'watch-pc2-cdp-self-heal\.ps1' }
) | Select-Object -First 1
if ($null -ne $existingSelfHeal) {
  Write-BootstrapLog -Event 'existing_watchdog_found' -Details @{ process_id = $existingSelfHeal.ProcessId }
  if ($Supervise) {
    Wait-WatchdogProcess -ProcessId $existingSelfHeal.ProcessId
  }
  return [pscustomobject]@{
    task_name = $TaskName
    task_path = $TaskPath
    task_state = 'ProcessRunning'
    launch_mode = 'already_running'
    active_session_id = [int]$activeSessionId
    process_id = $existingSelfHeal.ProcessId
  }
}

$taskAction = Get-TaskActionDefinition -Name $TaskName -Path $TaskPath
$actionWorkingDirectory = if ([string]::IsNullOrWhiteSpace($taskAction.working_directory)) {
  'C:\fapaifang-worker'
} else {
  [string]$taskAction.working_directory
}
$escapedActionExecute = ([string]$taskAction.execute).Replace("'", "''")
$escapedActionArguments = ([string]$taskAction.arguments).Replace("'", "''")
$escapedActionWorkingDirectory = $actionWorkingDirectory.Replace("'", "''")
$bootstrapResultPath = Join-Path 'C:\fapaifang-worker\state' ('interactive-task-bootstrap-{0}.json' -f [guid]::NewGuid().ToString('N'))
$actionStdoutPath = "$bootstrapResultPath.stdout.log"
$actionStderrPath = "$bootstrapResultPath.stderr.log"
$escapedResultPath = $bootstrapResultPath.Replace("'", "''")
$escapedStdoutPath = $actionStdoutPath.Replace("'", "''")
$escapedStderrPath = $actionStderrPath.Replace("'", "''")
$bootstrap = @"
`$result = [ordered]@{ success = `$false; task_state = 'Unknown'; process_id = 0; error = ''; stdout = ''; stderr = '' }
try {
  `$process = Start-Process -FilePath '$escapedActionExecute' -ArgumentList '$escapedActionArguments' -WorkingDirectory '$escapedActionWorkingDirectory' -WindowStyle Hidden -RedirectStandardOutput '$escapedStdoutPath' -RedirectStandardError '$escapedStderrPath' -PassThru -ErrorAction Stop
  Start-Sleep -Seconds 10
  `$result.process_id = `$process.Id
  `$result.success = -not `$process.HasExited
  `$result.task_state = if (`$result.success) { 'ProcessRunning' } else { 'Exited' }
  if (Test-Path -LiteralPath '$escapedStdoutPath') { `$result.stdout = Get-Content -LiteralPath '$escapedStdoutPath' -Raw -ErrorAction SilentlyContinue }
  if (Test-Path -LiteralPath '$escapedStderrPath') { `$result.stderr = Get-Content -LiteralPath '$escapedStderrPath' -Raw -ErrorAction SilentlyContinue }
} catch {
  `$result.error = `$_.Exception.Message
}
[IO.File]::WriteAllText('$escapedResultPath', (`$result | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding(`$false)))
"@
$encodedBootstrap = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($bootstrap))
$powerShellPath = Join-Path $PSHOME 'powershell.exe'
$commandLine = New-Object Text.StringBuilder
[void]$commandLine.Append(('"{0}" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand {1}' -f $powerShellPath, $encodedBootstrap))

$processHandle = [IntPtr]::Zero
$tokenHandle = [IntPtr]::Zero
$primaryToken = [IntPtr]::Zero
$environmentBlock = [IntPtr]::Zero
$processInfo = New-Object FapaiPc2.ActiveSessionProcess+PROCESS_INFORMATION
try {
  $isSystem = [Security.Principal.WindowsIdentity]::GetCurrent().IsSystem
  if ($isSystem) {
    $queriedToken = [FapaiPc2.ActiveSessionProcess]::WTSQueryUserToken(
      $activeSessionId,
      [ref]$primaryToken
    )
    Assert-Win32Result -Succeeded $queriedToken -Operation 'WTSQueryUserToken(active console)'
    $createdEnvironment = [FapaiPc2.ActiveSessionProcess]::CreateEnvironmentBlock(
      [ref]$environmentBlock,
      $primaryToken,
      $false
    )
    Assert-Win32Result -Succeeded $createdEnvironment -Operation 'CreateEnvironmentBlock(active console)'
  } else {
    $processHandle = [FapaiPc2.ActiveSessionProcess]::OpenProcess(0x1000, $false, $explorer.Id)
    Assert-Win32Result -Succeeded ($processHandle -ne [IntPtr]::Zero) -Operation 'OpenProcess(explorer.exe)'

    $openedToken = [FapaiPc2.ActiveSessionProcess]::OpenProcessToken(
      $processHandle,
      (0x0002 -bor 0x0008),
      [ref]$tokenHandle
    )
    Assert-Win32Result -Succeeded $openedToken -Operation 'OpenProcessToken(explorer.exe)'

    $duplicatedToken = [FapaiPc2.ActiveSessionProcess]::DuplicateTokenEx(
      $tokenHandle,
      0x02000000,
      [IntPtr]::Zero,
      2,
      1,
      [ref]$primaryToken
    )
    Assert-Win32Result -Succeeded $duplicatedToken -Operation 'DuplicateTokenEx(explorer.exe)'
  }

  $startupInfo = New-Object FapaiPc2.ActiveSessionProcess+STARTUPINFO
  $startupInfo.cb = [Runtime.InteropServices.Marshal]::SizeOf($startupInfo)
  $startupInfo.lpDesktop = 'winsta0\default'
  $startupInfo.dwFlags = 0x00000001
  $startupInfo.wShowWindow = 0
  if ($isSystem) {
    $created = [FapaiPc2.ActiveSessionProcess]::CreateProcessAsUserW(
      $primaryToken,
      $powerShellPath,
      $commandLine,
      [IntPtr]::Zero,
      [IntPtr]::Zero,
      $false,
      (0x08000000 -bor 0x00000400),
      $environmentBlock,
      'C:\fapaifang-worker',
      [ref]$startupInfo,
      [ref]$processInfo
    )
    Assert-Win32Result -Succeeded $created -Operation 'CreateProcessAsUserW(active console)'
  } else {
    $created = [FapaiPc2.ActiveSessionProcess]::CreateProcessWithTokenW(
      $primaryToken,
      0,
      $powerShellPath,
      $commandLine,
      0x08000000,
      [IntPtr]::Zero,
      'C:\fapaifang-worker',
      [ref]$startupInfo,
      [ref]$processInfo
    )
    Assert-Win32Result -Succeeded $created -Operation 'CreateProcessWithTokenW(active console)'
  }
  Write-BootstrapLog -Event 'interactive_launcher_started' -Details @{ process_id = $processInfo.dwProcessId }
} finally {
  if ($processInfo.hThread -ne [IntPtr]::Zero) {
    [void][FapaiPc2.ActiveSessionProcess]::CloseHandle($processInfo.hThread)
  }
  if ($processInfo.hProcess -ne [IntPtr]::Zero) {
    [void][FapaiPc2.ActiveSessionProcess]::CloseHandle($processInfo.hProcess)
  }
  if ($environmentBlock -ne [IntPtr]::Zero) {
    [void][FapaiPc2.ActiveSessionProcess]::DestroyEnvironmentBlock($environmentBlock)
  }
  if ($primaryToken -ne [IntPtr]::Zero) {
    [void][FapaiPc2.ActiveSessionProcess]::CloseHandle($primaryToken)
  }
  if ($tokenHandle -ne [IntPtr]::Zero) {
    [void][FapaiPc2.ActiveSessionProcess]::CloseHandle($tokenHandle)
  }
  if ($processHandle -ne [IntPtr]::Zero) {
    [void][FapaiPc2.ActiveSessionProcess]::CloseHandle($processHandle)
  }
}

$deadline = (Get-Date).AddSeconds([Math]::Max(10, $TimeoutSeconds))
try {
  do {
    Start-Sleep -Milliseconds 500
    if (-not (Test-Path -LiteralPath $bootstrapResultPath)) { continue }
    $bootstrapResult = Get-Content -LiteralPath $bootstrapResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($bootstrapResult.success -eq $true) {
      Write-BootstrapLog -Event 'watchdog_started' -Details @{ process_id = $bootstrapResult.process_id; task_state = [string]$bootstrapResult.task_state }
      if ($Supervise) {
        Wait-WatchdogProcess -ProcessId $bootstrapResult.process_id
      }
      return [pscustomobject]@{
        task_name = $TaskName
        task_path = $TaskPath
        task_state = [string]$bootstrapResult.task_state
        launch_mode = 'direct_action'
        active_session_id = [int]$activeSessionId
        process_id = $bootstrapResult.process_id
        bootstrap_process_id = $processInfo.dwProcessId
      }
    }
    $bootstrapError = [string]$bootstrapResult.error
    $actionError = [string]$bootstrapResult.stderr
    throw "Interactive bootstrap did not keep the action for scheduled task $TaskPath$TaskName running; state=$($bootstrapResult.task_state); error=$bootstrapError; stderr=$actionError"
  } while ((Get-Date) -lt $deadline)
  throw "Interactive bootstrap did not report a result for scheduled task $TaskPath$TaskName"
} finally {
  Remove-Item -LiteralPath $bootstrapResultPath, $actionStdoutPath, $actionStderrPath -Force -ErrorAction SilentlyContinue
}
