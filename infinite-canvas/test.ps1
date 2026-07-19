# 无限画布 · 一键测试（后端 pytest + 前端构建 + vitest）
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$agent = Join-Path $root 'agent'
$frontend = Join-Path $root 'frontend'
$py = Join-Path $agent '.venv/Scripts/python.exe'
$fail = 0

Write-Host '==== 后端 pytest ====' -ForegroundColor Cyan
Push-Location $agent
& $py -m pytest -q test_agent.py
if ($LASTEXITCODE -ne 0) { $fail = 1 }
Pop-Location

Write-Host '==== 前端构建（tsc strict + vite）====' -ForegroundColor Cyan
Push-Location $frontend
npm run build
if ($LASTEXITCODE -ne 0) { $fail = 1 }

Write-Host '==== 前端 vitest ====' -ForegroundColor Cyan
npm run test
if ($LASTEXITCODE -ne 0) { $fail = 1 }
Pop-Location

if ($fail -eq 0) {
    Write-Host 'ALL TESTS PASSED' -ForegroundColor Green
} else {
    Write-Host 'SOME TESTS FAILED' -ForegroundColor Red
    exit 1
}
