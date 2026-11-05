# 在 Windows 上构建 docmask.exe（也可由 GitHub Actions 自动执行）。
# 用法（PowerShell，在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts/build_windows_exe.ps1

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "==> 安装依赖"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

Write-Host "==> 运行测试"
python -m unittest discover -s tests -t .

Write-Host "==> 构建 docmask.exe"
python -m PyInstaller --noconfirm --clean docmask.spec

if (-not (Test-Path "dist\docmask.exe")) {
    throw "构建失败：未找到 dist\docmask.exe"
}
if (-not (Test-Path "dist\docmask-cli.exe")) {
    throw "构建失败：未找到 dist\docmask-cli.exe"
}

Write-Host "==> 冒烟测试"
& "dist\docmask-cli.exe" --version

Write-Host "==> 打包 ZIP 与校验和"
New-Item -ItemType Directory -Force dist\package | Out-Null
Copy-Item dist\docmask.exe dist\package\
Copy-Item dist\docmask-cli.exe dist\package\
Copy-Item README.md dist\package\
Copy-Item examples dist\package\examples -Recurse
Compress-Archive -Force -Path "dist\package\*" -DestinationPath "dist\docmask-windows-x64.zip"
$hash = (Get-FileHash "dist\docmask-windows-x64.zip" -Algorithm SHA256).Hash.ToLower()
"$hash  docmask-windows-x64.zip" | Out-File -Encoding ascii "dist\SHA256SUMS.txt"

Write-Host "完成：dist\docmask-windows-x64.zip"
