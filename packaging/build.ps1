# 《免疫防线》打包脚本（开发者机）
# 用法：powershell -ExecutionPolicy Bypass -File packaging\build.ps1
# 产物：packaging\dist\免疫防线\（onedir）+ zip 压缩包
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "[1/3] 安装/检查 PyInstaller ..."
python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    pip install pyinstaller
}

Write-Host "[2/3] PyInstaller 构建（onedir）..."
Push-Location $root
python -m PyInstaller --noconfirm packaging\immunedefense.spec
Pop-Location

Write-Host "[3/3] 打包 zip（校验不含玩家档案）..."
$dist = Join-Path $root "packaging\dist\免疫防线"
if (-not (Test-Path (Join-Path $dist "免疫防线.exe"))) {
    throw "构建产物缺失：$dist"
}
# 分发洁净化检查：成品目录绝不允许出现玩家存档/数据库
$leak = Get-ChildItem $dist -Recurse -Include "meta.json","meta.json.migrated","config.json","userdata","*.db" -ErrorAction SilentlyContinue
if ($leak) {
    throw "分发产物包含玩家档案：$($leak.FullName -join ', ')"
}
$zip = Join-Path $root "packaging\免疫防线-v5-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip
Write-Host "完成：$zip"
