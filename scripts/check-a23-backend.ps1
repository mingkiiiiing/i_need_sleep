param(
    [int]$Port = 8000,
    [int]$TimeoutSeconds = 5
)

$ErrorActionPreference = 'Stop'
$expectedProductId = 'taihu-a23-algae-warning'
$uri = "http://127.0.0.1:$Port/api/health"

try {
    $response = Invoke-RestMethod -Uri $uri -TimeoutSec $TimeoutSeconds
} catch {
    Write-Error "A23 后端身份检查失败：$uri 不可用。$($_.Exception.Message)"
    exit 2
}

$data = $response.data
if ($response.code -ne 200 -or $data.status -ne 'ok' -or $data.product_id -ne $expectedProductId) {
    $actual = if ($data.product_id) { $data.product_id } elseif ($data.service) { $data.service } else { 'unknown-service' }
    Write-Error "端口 $Port 不是太湖 A23 后端：期望 product_id=$expectedProductId，实际=$actual。请勿继续启动前端代理。"
    exit 3
}

Write-Output "A23_BACKEND_OK port=$Port product_id=$($data.product_id) version=$($data.api_version)"
