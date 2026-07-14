$ErrorActionPreference = "Stop"

python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name "发票识别工具" `
    --add-data "build-assets/tesseract;tesseract" `
    --collect-all pypdfium2 `
    invoice_app.py

$releaseRoot = "release/发票识别工具"
Remove-Item -Recurse -Force "release" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
Copy-Item -Path "dist/发票识别工具/*" -Destination $releaseRoot -Recurse -Force
Copy-Item -Path "THIRD_PARTY_NOTICES.md" -Destination $releaseRoot
Compress-Archive -Path $releaseRoot -DestinationPath "release/invoice-renamer-windows.zip" -Force
