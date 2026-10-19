param(
    [string]$OutputDirectory = "build-assets/tesseract"
)

$ErrorActionPreference = "Stop"

choco install tesseract --yes --no-progress
if ($LASTEXITCODE -ne 0) { throw "Tesseract installation failed" }

$tesseractDirectory = Join-Path $env:ProgramFiles "Tesseract-OCR"
if (-not (Test-Path (Join-Path $tesseractDirectory "tesseract.exe"))) {
    throw "Chocolatey did not install Tesseract at the expected location."
}

$workspace = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$OutputDirectory = [IO.Path]::GetFullPath((Join-Path $workspace $OutputDirectory))
$allowedRoot = (Join-Path $workspace "build-assets") + [IO.Path]::DirectorySeparatorChar
if (-not $OutputDirectory.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OCR output must stay inside build-assets"
}
if (Test-Path -LiteralPath $OutputDirectory) { Remove-Item -LiteralPath $OutputDirectory -Recurse -Force }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
Copy-Item -Path (Join-Path $tesseractDirectory "*") -Destination $OutputDirectory -Recurse -Force

$tessdataDirectory = Join-Path $OutputDirectory "tessdata"
New-Item -ItemType Directory -Path $tessdataDirectory -Force | Out-Null
Invoke-WebRequest `
    -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/chi_sim.traineddata" `
    -OutFile (Join-Path $tessdataDirectory "chi_sim.traineddata")
