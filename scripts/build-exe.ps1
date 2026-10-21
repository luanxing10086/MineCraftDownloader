<#
.SYNOPSIS
    构建单文件 mcdl.exe（PyInstaller），可选自动签名。

.DESCRIPTION
    pip 在受限网络里可能卡住，所以依赖改为“直接抓 wheel 再解包”的方式获取；
    若本机已有可用的代码签名证书（CurrentUser\My 中 subject 含 mcdonloader），
    会给产物签名并更新 SHA256SUMS.txt。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
#>
param(
    [string]$BuildDir = 'F:\DSH-WORK\.build',
    [string]$Python = 'python',
    [string]$OutDir = 'F:\DSH-WORK\dist'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $BuildDir 'venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    Write-Host "==> 创建 venv" -ForegroundColor Cyan
    & $Python -m venv $venv
}

$lib = Join-Path $BuildDir 'pylib'
if (-not (Test-Path (Join-Path $lib 'PyInstaller'))) {
    Write-Host "==> 获取 PyInstaller" -ForegroundColor Cyan
    & $venvPython (Join-Path $PSScriptRoot 'fetch_wheels.py') `
        --dest-wheels (Join-Path $BuildDir 'wheels') --dest-lib $lib
}

Write-Host "==> 打包" -ForegroundColor Cyan
$env:PYTHONPATH = $lib
$env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildDir 'pyi-cache'
& $venvPython -m PyInstaller --onefile --console --noconfirm --name mcdl `
    --paths $repo `
    --distpath (Join-Path $BuildDir 'dist') `
    --workpath (Join-Path $BuildDir 'work') `
    --specpath $BuildDir `
    (Join-Path $repo 'tools\mcdl_entry.py') | Select-Object -Last 3

$exe = Join-Path $BuildDir 'dist\mcdl.exe'
if (-not (Test-Path $exe)) { throw '打包失败：找不到 dist\mcdl.exe' }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$outExe = Join-Path $OutDir 'mcdl.exe'
Copy-Item $exe $outExe -Force
Write-Host "==> 产物：$outExe（$([math]::Round((Get-Item $outExe).Length / 1MB, 1)) MB）" -ForegroundColor Green

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -like '*mcdonloader*' } | Select-Object -First 1
if ($cert) {
    Write-Host "==> 使用证书 $($cert.Thumbprint) 签名" -ForegroundColor Cyan
    try {
        $sig = Set-AuthenticodeSignature -FilePath $outExe -Certificate $cert `
            -TimestampServer 'http://timestamp.digicert.com' -HashAlgorithm SHA256
    } catch {
        $sig = Set-AuthenticodeSignature -FilePath $outExe -Certificate $cert -HashAlgorithm SHA256
    }
    Write-Host "    签名状态：$($sig.Status)" -ForegroundColor Green
} else {
    Write-Host "==> 未找到签名证书，跳过签名" -ForegroundColor Yellow
}

$hash = (Get-FileHash $outExe -Algorithm SHA256).Hash.ToLower()
"$hash *mcdl.exe" | Set-Content (Join-Path $OutDir 'SHA256SUMS.txt') -Encoding ASCII
Write-Host "==> SHA256：$hash" -ForegroundColor Green
