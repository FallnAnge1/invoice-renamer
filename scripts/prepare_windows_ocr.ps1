param(
    [string]$OutputDirectory = "build-assets/tesseract"
)

$ErrorActionPreference = "Stop"

choco install tesseract --yes --no-progress

$tesseractDirectory = Join-Path $env:ProgramFiles "Tesseract-OCR"
if (-not (Test-Path (Join-Path $tesseractDirectory "tesseract.exe"))) {
    throw "未找到 Chocolatey 安装的 Tesseract。"
}

Remove-Item -Recurse -Force $OutputDirectory -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
Copy-Item -Path (Join-Path $tesseractDirectory "*") -Destination $OutputDirectory -Recurse -Force

$tessdataDirectory = Join-Path $OutputDirectory "tessdata"
New-Item -ItemType Directory -Path $tessdataDirectory -Force | Out-Null
Invoke-WebRequest `
    -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/chi_sim.traineddata" `
    -OutFile (Join-Path $tessdataDirectory "chi_sim.traineddata")
