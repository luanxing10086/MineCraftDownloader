<#
.SYNOPSIS
    把 onedir 构建打包成 MSIX（用于微软商店提交或本地侧载测试）。

.DESCRIPTION
    - 从 packaging\AppxManifest.template.xml 渲染清单
    - 自动生成商店需要的几张图标（若缺失）
    - 调用 Windows SDK 的 makeappx.exe 打包，并做一次校验
    - 可选：用本机自签名证书签名（仅用于本地侧载；商店提交不要签，Store 会重签）

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 -InputDir F:\DSH-WORK\.build\onedir2\MCD-GUI

.EXAMPLE
    # 拿到 Partner Center 的包标识后：
    powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 `
        -InputDir <onedir> -IdentityName 12345Publisher.MCD -Publisher "CN=xxxxxxxx-...." -Version 0.1.0.0
#>
param(
    [Parameter(Mandatory = $true)][string]$InputDir,
    [string]$OutputDir = 'F:\DSH-WORK\dist',
    [string]$IdentityName = 'MCD.MinecraftDownloader',
    [string]$Publisher = 'CN=mcdonloader self-signed, O=mcdonloader',
    [string]$PublisherDisplayName = 'MCD',
    [string]$Version = '0.1.0.0',
    [string]$Description = 'Minecraft 下载器：原版、加载器版本、整合包',
    [string]$MakeAppx = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\makeappx.exe',
    [string]$SignTool = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.22000.0\x64\signtool.exe',
    [switch]$Sign
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

# 自动找可用的 makeappx / signtool（不同机器 SDK 版本不同）
function Find-SdkTool([string]$name) {
    $root = 'C:\Program Files (x86)\Windows Kits\10\bin'
    $found = Get-ChildItem $root -Recurse -Filter $name -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\' } |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
    return ''
}
if (-not (Test-Path $MakeAppx)) { $MakeAppx = Find-SdkTool 'makeappx.exe' }
if (-not (Test-Path $SignTool)) { $SignTool = Find-SdkTool 'signtool.exe' }
if (-not (Test-Path $MakeAppx)) { throw '找不到 makeappx.exe，请安装 Windows 10/11 SDK' }

$stage = Join-Path $env:TEMP ("mcd-msix-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$assets = Join-Path $stage 'Assets'
New-Item -ItemType Directory -Force -Path $assets | Out-Null

Write-Host "==> 复制应用文件" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $InputDir 'MCD-GUI.exe'))) {
    throw "InputDir 里没有 MCD-GUI.exe：$InputDir"
}
Copy-Item "$InputDir\*" $stage -Recurse -Force

Write-Host "==> 生成图标" -ForegroundColor Cyan
Add-Type -AssemblyName System.Drawing
$sizes = @(
    @{Name = 'StoreLogo.png'; W = 50; H = 50},
    @{Name = 'Square44x44Logo.png'; W = 44; H = 44},
    @{Name = 'Square71x71Logo.png'; W = 71; H = 71},
    @{Name = 'Square150x150Logo.png'; W = 150; H = 150},
    @{Name = 'Wide310x150Logo.png'; W = 310; H = 150}
)
foreach ($spec in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap $spec.W, $spec.H
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.Clear([System.Drawing.ColorTranslator]::FromHtml('#1E1E1E'))
    $fontSize = [math]::Max(10, [int]($spec.H * 0.34))
    $font = New-Object System.Drawing.Font 'Segoe UI', $fontSize, ([System.Drawing.FontStyle]::Bold)
    $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml('#4CC2FF'))
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = 'Center'
    $fmt.LineAlignment = 'Center'
    $rect = New-Object System.Drawing.RectangleF 0, 0, $spec.W, $spec.H
    $g.DrawString('MCD', $font, $brush, $rect, $fmt)
    $g.Dispose()
    $bmp.Save((Join-Path $assets $spec.Name), [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
}

Write-Host "==> 渲染清单" -ForegroundColor Cyan
$template = Get-Content (Join-Path $repo 'packaging\AppxManifest.template.xml') -Raw -Encoding UTF8
$manifest = $template.Replace('__IDENTITY_NAME__', $IdentityName).
    Replace('__PUBLISHER__', $Publisher).
    Replace('__PUBLISHER_DISPLAY_NAME__', $PublisherDisplayName).
    Replace('__VERSION__', $Version).
    Replace('__DESCRIPTION__', $Description)
$utf8bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText((Join-Path $stage 'AppxManifest.xml'), $manifest, $utf8bom)

Write-Host "==> 打包 MSIX" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$msix = Join-Path $OutputDir ("MCD_" + $Version + "_x64.msix")
if (Test-Path $msix) { Remove-Item $msix -Force }
& $MakeAppx pack /d $stage /p $msix /o | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { throw "makeappx 失败（退出码 $LASTEXITCODE）" }

Write-Host "==> 校验清单" -ForegroundColor Cyan
& $MakeAppx validate /d $stage | Select-Object -Last 3

if ($Sign) {
    $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
        Where-Object { $_.Subject -like '*mcdonloader*' } | Select-Object -First 1
    if (-not $cert) { throw '未找到本机自签名证书，无法签名' }
    Write-Host "==> 用本机证书签名（仅侧载测试，商店提交不需要）" -ForegroundColor Cyan
    & $SignTool sign /fd SHA256 /sha1 $cert.Thumbprint $msix | Select-Object -Last 3
}

$hash = (Get-FileHash $msix -Algorithm SHA256).Hash.ToLower()
"产物: $msix"
"大小: $([math]::Round((Get-Item $msix).Length / 1MB, 1)) MB"
"SHA256: $hash"
Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue
