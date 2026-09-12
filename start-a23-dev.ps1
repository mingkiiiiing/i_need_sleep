param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir 'backend/.venv/Scripts/python.exe'
$healthUri = "http://127.0.0.1:$BackendPort/api/health"
$expectedProductId = 'taihu-a23-algae-warning'

function Get-A23Health {
    try { return Invoke-RestMethod -Uri $healthUri -TimeoutSec 2 } catch { return $null }
}

$portOwner = Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue | Select-Object -First 1
if ($portOwner) {
    $health = Get-A23Health
    if ($health.data.product_id -ne $expectedProductId) {
        $processName = (Get-Process -Id $portOwner.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        throw "端口 $BackendPort 已被非 A23 服务占用（PID=$($portOwner.OwningProcess), process=$processName）。为避免前端连接错误项目，启动已终止。"
    }
    Write-Output "复用已运行的 A23 后端：$healthUri"
} else {
    if (!(Test-Path -LiteralPath $pythonExe)) { throw "未找到项目 Python：$pythonExe" }
    Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',"$BackendPort") -WorkingDirectory $projectDir -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 500
        $health = Get-A23Health
    } until ($health.data.product_id -eq $expectedProductId -or (Get-Date) -gt $deadline)
    if ($health.data.product_id -ne $expectedProductId) { throw "A23 后端在 45 秒内未通过身份检查：$healthUri" }
    Write-Output "A23 后端已启动并通过身份检查：$healthUri"
}

$env:BACKEND_ORIGIN = "http://127.0.0.1:$BackendPort"
Start-Process -FilePath 'npm.cmd' -ArgumentList @('run','dev','--','--port',"$FrontendPort") -WorkingDirectory $projectDir -WindowStyle Hidden
Write-Output "A23 前端已启动：http://127.0.0.1:$FrontendPort"
