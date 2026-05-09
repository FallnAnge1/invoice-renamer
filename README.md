# 发票识别与重命名工具

支持命令行和 Windows 图形界面两种使用方式。

## 命令行用法

```bash
python3 rename_invoices.py invoice.pdf           # 处理单文件
python3 rename_invoices.py --dry-run invoice.pdf # 预览模式
python3 rename_invoices.py ~/Desktop/invoices/   # 批量处理
```

## Windows 图形界面

```bash
python invoice_app.py
```

功能：
- 添加 PDF 文件或导入整个文件夹
- 预览识别结果（购买方名称 + 金额）
- 双击表格单元格可手动修正
- 一键批量重命名
- 右键删除不需要的文件

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
