@echo off
chcp 65001 >nul
echo ========================================
echo   发票识别工具 - Windows 打包脚本
echo ========================================
echo.

:: 自动查找 Python
set PYTHON=
for /f "tokens=*" %%i in ('where python 2^>nul') do set PYTHON=%%i
if not defined PYTHON for /f "tokens=*" %%i in ('where python3 2^>nul') do set PYTHON=%%i

:: 如果 path 里没有，搜索常见安装位置
if not defined PYTHON (
    for %%v in (313 312 311 310 39) do (
        if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe" (
            set PYTHON=%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe
            goto :found
        )
        if exist "C:\Python%%v\python.exe" (
            set PYTHON=C:\Python%%v\python.exe
            goto :found
        )
    )
    :: Microsoft Store 版本
    if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
        set PYTHON=%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe
    )
)

:found
if not defined PYTHON (
    echo [错误] 未找到 Python，请重新安装并勾选 "Add Python to PATH"
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo 找到 Python: %PYTHON%
"%PYTHON%" --version

echo.
echo [1/3] 安装依赖...
"%PYTHON%" -m pip install pdfplumber pdf2image Pillow pytesseract pyinstaller rarfile py7zr

echo.
echo [2/3] 打包为 exe（约 2-3 分钟）...
"%PYTHON%" -m PyInstaller --onefile --windowed --name "发票识别工具" ^
    invoice_app.py

echo.
echo [3/3] 打包完成！
echo.
echo 可执行文件: dist\发票识别工具.exe
echo.
pause
