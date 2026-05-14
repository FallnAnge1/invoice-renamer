# 发票识别与重命名工具

Windows 图形界面程序，用于识别 PDF 发票中的购买方名称和金额并批量重命名。

## 使用方法

```bash
python invoice_app.py
```

功能：
- 添加 PDF 文件或导入整个文件夹
- **添加压缩包（.zip/.rar/.7z），自动解压到桌面并导入 PDF**
- 预览识别结果（购买方名称 + 金额）
- 双击表格单元格可手动修正
- 一键批量重命名
- 右键删除不需要的文件

> 支持 RAR 需安装：`pip install rarfile`；支持 7Z 需安装：`pip install py7zr`。ZIP 无需额外依赖。

### 打包为独立 .exe

1. 在 Windows 上安装 Python 3.9+
2. 双击运行 `build.bat`
3. 完成后在 `dist\发票识别工具.exe` 找到可执行文件
4. 该 .exe 可独立运行，无需安装 Python

## 重命名规则

`{购买方名称}_{金额}.pdf`，重名自动加序号。

## OCR 支持（扫描件发票）

Windows 安装 tesseract：https://github.com/UB-Mannheim/tesseract/wiki

macOS：`brew install tesseract tesseract-lang`
