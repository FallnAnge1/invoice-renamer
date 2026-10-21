param([string]$PythonExecutable = "python")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
foreach ($file in @("tesseract.exe", "tessdata/chi_sim.traineddata", "tessdata/eng.traineddata")) {
    if (-not (Test-Path (Join-Path "build-assets/tesseract" $file))) {
        throw "Missing bundled OCR resource: $file. Run prepare_windows_ocr.ps1 first."
    }
}
& $PythonExecutable scripts/build_app_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }
$version = (& $PythonExecutable -c "from app_version import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid application version" }
$parts = $version.Split('.')
$versionResource = @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($($parts[0]),$($parts[1]),$($parts[2]),0), prodvers=($($parts[0]),$($parts[1]),$($parts[2]),0), mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
  kids=[StringFileInfo([StringTable('080404B0',[
    StringStruct('CompanyName','FallnAnge1'),
    StringStruct('FileDescription','发票与文档助手'),
    StringStruct('FileVersion','$version'),
    StringStruct('InternalName','InvoiceDocumentAssistant'),
    StringStruct('OriginalFilename','invoice-renamer-windows.exe'),
    StringStruct('ProductName','发票与文档助手'),
    StringStruct('ProductVersion','$version')
  ])]),VarFileInfo([VarStruct('Translation',[2052,1200])])])
"@
[IO.File]::WriteAllText((Join-Path (Get-Location) "build-assets/windows-version.txt"), $versionResource, [Text.UTF8Encoding]::new($false))
& $PythonExecutable -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name "发票与文档助手" `
    --icon "assets/app.ico" `
    --version-file "build-assets/windows-version.txt" `
    --add-data "build-assets/tesseract;tesseract" `
    --add-data "assets;assets" `
    --add-data "THIRD_PARTY_NOTICES.md;." `
    --add-data "使用说明.txt;." `
    --collect-all pypdfium2 `
    invoice_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$workspace = (Get-Location).Path
$releaseDirectory = [IO.Path]::GetFullPath((Join-Path $workspace "release"))
if ($releaseDirectory -ne (Join-Path $workspace "release")) { throw "Unsafe release directory" }
if (Test-Path -LiteralPath $releaseDirectory) {
    Remove-Item -LiteralPath $releaseDirectory -Recurse -Force
}
New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null
$executable = Join-Path $releaseDirectory "invoice-renamer-windows.exe"
Copy-Item -LiteralPath "dist/发票与文档助手.exe" -Destination $executable
Copy-Item -Path "THIRD_PARTY_NOTICES.md", "使用说明.txt" -Destination $releaseDirectory
$digest = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$executable.sha256", "$digest  invoice-renamer-windows.exe`n", [Text.UTF8Encoding]::new($false))
Write-Host "Single EXE ready: $executable (SHA256 $digest)"
