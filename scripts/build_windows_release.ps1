param([string]$PythonExecutable = "python")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
foreach ($file in @("tesseract.exe", "tessdata/chi_sim.traineddata", "tessdata/eng.traineddata")) {
    if (-not (Test-Path (Join-Path "build-assets/tesseract" $file))) {
        throw "Missing bundled OCR resource: $file. Run prepare_windows_ocr.ps1 first."
    }
}
& $PythonExecutable -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name "发票识别工具" `
    --add-data "build-assets/tesseract;tesseract" `
    --collect-all pypdfium2 `
    invoice_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$workspace = (Get-Location).Path
$releaseDirectory = [IO.Path]::GetFullPath((Join-Path $workspace "release"))
if ($releaseDirectory -ne (Join-Path $workspace "release")) { throw "Unsafe release directory" }
if (Test-Path -LiteralPath $releaseDirectory) {
    Remove-Item -LiteralPath $releaseDirectory -Recurse -Force
}
$releaseRoot = Join-Path $releaseDirectory "发票识别工具"
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
Copy-Item -Path "dist/发票识别工具/*" -Destination $releaseRoot -Recurse -Force
Copy-Item -Path "THIRD_PARTY_NOTICES.md", "使用说明.txt" -Destination $releaseRoot
$archive = Join-Path $releaseDirectory "invoice-renamer-windows.zip"
Compress-Archive -Path $releaseRoot -DestinationPath $archive
$digest = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$archive.sha256", "$digest  invoice-renamer-windows.zip`n", [Text.UTF8Encoding]::new($false))
Write-Host "Package ready: $archive (SHA256 $digest)"
