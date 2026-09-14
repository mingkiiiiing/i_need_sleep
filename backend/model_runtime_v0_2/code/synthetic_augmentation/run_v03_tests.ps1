#requires -Version 7.0
param([string]$Pattern = "test_*.py", [string]$LogPath = "")

[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$trainingRoot = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '..')).FullName
$projectRoot = (Get-Item -LiteralPath (Join-Path $trainingRoot '..')).FullName
$runtimePath = (Get-Item -LiteralPath (Join-Path $trainingRoot '.runtime\v03')).FullName
$testRoot = (Get-Item -LiteralPath (Join-Path $PSScriptRoot 'tests')).FullName
$pythonExe = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path -LiteralPath $runtimePath -PathType Container)) { throw "Project-scoped runtime cache missing: $runtimePath" }
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) { throw "Bundled Python missing: $pythonExe" }

# requirements-v03.txt is the human-readable direct requirements reference only.
# Fresh reproducible provisioning (from the bundled runtime): bundled python -m pip install --target <project runtime path> -r requirements-v03.lock.txt
$oldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = "$runtimePath;$(Join-Path $projectRoot '训练准备')"
    $output = (& $pythonExe -m unittest discover -s $testRoot -p $Pattern 2>&1 | Out-String)
    $code = $LASTEXITCODE
    $report = "$output`nTEST_EXIT_CODE=$code"
    Write-Output $report
    if ($LogPath) { Set-Content -LiteralPath $LogPath -Value $report -Encoding UTF8 }
    # A successful run must contain unittest's exact `Ran <n> test(s)` summary and `OK`.
    if ($code -eq 0 -and ($output -notmatch '(?m)^Ran \d+ tests? in ') -or ($code -eq 0 -and $output -notmatch '(?m)^OK\s*$')) { $code = 1 }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
exit $code
