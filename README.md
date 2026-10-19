# 发票识别与重命名工具

Windows 图形界面程序，用于识别 PDF 发票中的购买方名称、日期、金额和发票号码并批量重命名。

## 使用方法

```bash
python invoice_app.py
```

功能：
- 添加 PDF 文件或导入整个文件夹
- **添加压缩包（.zip/.rar/.7z），自动解压到桌面并导入 PDF**
- 预览识别结果（购买方名称、开票日期、金额、发票号码）
- 双击识别字段可手动修正
- 一键批量重命名
- 支持导出 CSV 识别记录，并在本次打开软件期间撤销上一次重命名
- 右键删除不需要的文件
- **格式转换：图片转 PDF、多图合并 PDF、PDF 转 PNG/JPG、图片互转、PDF 合并和逐页拆分**

## 格式转换

点击主界面的 **格式转换（图片 / PDF）**，选择转换方式，添加文件并选择输出文件夹，点击“开始转换”。

| 功能 | 说明 |
| --- | --- |
| 图片转 PDF | 每张图片单独生成 PDF，或按列表顺序合并为一份多页 PDF |
| PDF 转图片 | 每页输出一张 PNG 或 JPG，150 DPI |
| 图片互转 | JPG、PNG、WebP、BMP、单帧 TIFF 可作为输入；输出 JPG、PNG、WebP、BMP |
| PDF 合并 | 按列表顺序合并多份 PDF，可用上移、下移调整 |
| PDF 拆分 | 每页生成独立 PDF |

转换在本机完成，原文件保留，已有同名输出自动加序号。透明图片转 JPG/BMP/PDF 时使用白底，自动校正手机照片的 EXIF 方向。
多帧 TIFF 等图片会提示先拆帧，避免只导出第一页。加密且需要密码的 PDF 会报告失败。
独立批量转换遇到坏文件会继续处理其他文件；合并遇错则不生成残缺合并文件。失败详情在窗口中显示。

勾选“完成后将生成的 PDF 加入发票列表”，即可继续预览识别和重命名；图片生成的 PDF 仍需 OCR。
Word/Excel 与 PDF 的互转不包含在本版功能内。转换后的 PDF 不保证保留原文档签名或交互表单功能。

以上转换使用项目已有的 Pillow 和 PDFium，无需新增转换软件。

> 支持 RAR 需安装：`pip install rarfile`；支持 7Z 需安装：`pip install py7zr`。ZIP 无需额外依赖。

### 打包为独立 .exe

1. 在 Windows 上安装 Python 3.9+
2. 双击运行 `build.bat`
3. 完成后在 `dist\发票识别工具.exe` 找到可执行文件
4. 官方 Release 版会提供包含 OCR 引擎的压缩包；解压后双击 `.exe` 即可使用扫描件识别。

## 重命名规则

默认格式为：

`{开票日期}_{购买方名称}_{金额}_{发票号码后8位}.pdf`

识别不到日期或发票号码时会自动省略对应字段；重名自动加序号。

## OCR 支持（扫描件发票）

从 GitHub Release 下载的 Windows 压缩包已内置 Tesseract 和中文识别数据，**无需单独安装 Tesseract 或 Poppler**。

如果直接通过 `python invoice_app.py` 运行源码，扫描件识别仍需自行安装 Tesseract：

- Windows：https://github.com/UB-Mannheim/tesseract/wiki
- macOS：`brew install tesseract tesseract-lang`

程序使用内置的 PDFium 渲染扫描件，不再依赖 Poppler。
