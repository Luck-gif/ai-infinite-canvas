# 无限画布 · 一键启动（Windows PowerShell）
# 用法：  ./start.ps1        启动后端(8000) + 前端 dev(5173)
#         ./start.ps1 -Prod  启动后端 + 前端预览(4173, 需先 npm run build)
param(
    [switch]$Prod
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$agent = Join-Path $root 'agent'
$frontend = Join-Path $root 'frontend'
$py = Join-Path $agent '.venv/Scripts/python.exe'

if (-not (Test-Path $py)) {
    Write-Host '[start] 未找到 agent/.venv，请先创建虚拟环境并安装依赖：' -ForegroundColor Yellow
    Write-Host '        python -m venv agent/.venv; agent/.venv/Scripts/pip install -r agent/requirements.txt'
    exit 1
}

# 1) 后端 uvicorn（8000）
Write-Host '[start] 启动后端 uvicorn :8000 ...' -ForegroundColor Cyan
Start-Process -FilePath $py `
    -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000' `
    -WorkingDirectory $agent `
    -RedirectStandardOutput (Join-Path $agent 'uvicorn.out.log') `
    -RedirectStandardError (Join-Path $agent 'uvicorn.err.log')

Start-Sleep -Seconds 3

# 2) 前端
if ($Prod) {
    Write-Host '[start] 启动前端预览 :4173 ...' -ForegroundColor Cyan
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run preview' -WorkingDirectory $frontend
    $url = 'http://localhost:4173'
} else {
    Write-Host '[start] 启动前端 dev :5173 ...' -ForegroundColor Cyan
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm run dev' -WorkingDirectory $frontend
    $url = 'http://localhost:5173'
}

Start-Sleep -Seconds 4
Write-Host "[start] 就绪。请访问 $url" -ForegroundColor Green
Write-Host '[start] 后端健康检查： http://127.0.0.1:8000/health'
