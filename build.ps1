# JAVCover release builder
#
# Produces a Python-free distribution so end users do not need Python installed.
# Usage (from the project root, PowerShell):
#   .\build.ps1                 # onedir + onefile + portable zip in .\release
#   .\build.ps1 -Mode onedir    # only the folder build
#   .\build.ps1 -Mode onefile   # only the single exe
#   .\build.ps1 -Icon path\to\app.ico
param(
    [ValidateSet("both", "onedir", "onefile")]
    [string]$Mode = "both",
    [string]$Icon = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到 .venv\Scripts\python.exe。请先创建虚拟环境并安装依赖：py -3 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ."
}

$release = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $release | Out-Null

& $python -m pip install -e ".[build]"

$common = @(
    "--noconfirm", "--clean", "--windowed",
    "--name", "JAVCover",
    "--paths", "src",
    "--add-data", "src\javcover\icons;javcover\icons"
)

# 生成 exe 图标：默认从 src\javcover\icons\app-icon.svg 转换；也可用 -Icon 指定 .ico
$defaultSvg = Join-Path $root "src\javcover\icons\app-icon.svg"
$generatedIco = Join-Path $root "build\app.ico"
if ($Icon) {
    $iconPath = (Resolve-Path -LiteralPath $Icon).Path
} elseif (Test-Path -LiteralPath $defaultSvg) {
    & $python (Join-Path $root "tools\make_icon.py") $defaultSvg $generatedIco
    $iconPath = $generatedIco
} else {
    $iconPath = ""
}
if ($iconPath -and (Test-Path -LiteralPath $iconPath)) {
    $common += @("--icon", $iconPath)
    Write-Host "使用图标：$iconPath"
}

$entry = Join-Path $root "run_javcover.py"

if ($Mode -in @("both", "onedir")) {
    Write-Host "== 构建目录版 (onedir) =="
    & $python -m PyInstaller @common $entry
    $zip = Join-Path $release "JAVCover-portable.zip"
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -Path (Join-Path $root "dist\JAVCover\*") -DestinationPath $zip
    Write-Host "便携目录版：dist\JAVCover\  压缩包：$zip"
}

if ($Mode -in @("both", "onefile")) {
    Write-Host "== 构建单文件版 (onefile) =="
    $onefileDist = Join-Path $root "dist-onefile"
    & $python -m PyInstaller @common --onefile --distpath $onefileDist $entry
    Copy-Item -LiteralPath (Join-Path $onefileDist "JAVCover.exe") -Destination (Join-Path $release "JAVCover.exe") -Force
    Write-Host "单文件版：release\JAVCover.exe"
}

Write-Host ""
Write-Host "完成。发布内容位于：$release"
Write-Host "- release\JAVCover.exe           单文件便携版（双击即用，无需安装）"
Write-Host "- release\JAVCover-portable.zip  目录版压缩包（解压后运行 JAVCover.exe）"
Write-Host "- 生成安装程序：用 Inno Setup 打开 installer\JAVCover.iss 编译"
