<#
.SYNOPSIS
    构建 mcdl 的可执行文件（PyInstaller）。默认构建命令行版，加 -Gui 构建图形界面版。

.DESCRIPTION
    pip 在受限网络里可能卡住，所以依赖改为“直接抓 wheel 再解包”的方式获取；
    若本机有可用的代码签名证书（CurrentUser\My 中 subject 含 mcdonloader），会给产物签名。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
    powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1 -Gui
#>
param(
    [string]$BuildDir = 'F:\DSH-WORK\.build',
    [string]$Python = 'python',
    [string]$OutDir = 'F:\DSH-WORK\dist',
    [switch]$Gui
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

if ($Gui) {
    $entry = Join-Path $repo 'tools\gui_entry.py'
    $name = 'mcdl-gui'
    $mode = @('--windowed')
} else {
    $entry = Join-Path $repo 'tools\mcdl_entry.py'
    $name = 'mcdl'
    $mode = @('--console')
}

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

Write-Host "==> 打包 $name" -ForegroundColor Cyan
$env:PYTHONPATH = $lib
$env:PYINSTALLER_CONFIG_DIR = Join-Path $BuildDir 'pyi-cache'
& $venvPython -m PyInstaller --onefile --noconfirm --name $name @mode `
    --paths $repo `
    --distpath (Join-Path $BuildDir 'dist') `
    --workpath (Join-Path $BuildDir "work-$name") `
    --specpath $BuildDir `
    $entry | Select-Object -Last 3

$exe = Join-Path $BuildDir "dist\$name.exe"
if (-not (Test-Path $exe)) { throw "打包失败：找不到 $name.exe" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$outExe = Join-Path $OutDir "$name.exe"
Copy-Item $exe $outExe -Force
Write-Host "==> 产物：$outExe（$([math]::Round((Get-Item $outExe).Length / 1MB, 1)) MB）" -ForegroundColor Green

$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -like '*mcdonloader*' } | Select-Object -First 1
if ($cert) {
    try {
        Write-Host "==> 使用证书 $($cert.Thumbprint) 签名" -ForegroundColor Cyan
        $sig = Set-AuthenticodeSignature -FilePath $outExe -Certificate $cert `
            -TimestampServer 'http://timestamp.digicert.com' -HashAlgorithm SHA256
        Write-Host "    签名状态：$($sig.Status)" -ForegroundColor Green
    } catch {
        Write-Host "    签名失败（权限或网络原因），保持未签名：$($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Host "==> 未找到签名证书，跳过签名" -ForegroundColor Yellow
}

$hash = (Get-FileHash $outExe -Algorithm SHA256).Hash.ToLower()
"$hash *$name.exe" | Add-Content (Join-Path $OutDir 'SHA256SUMS.txt') -Encoding ASCII
Write-Host "==> SHA256：$hash" -ForegroundColor Green
