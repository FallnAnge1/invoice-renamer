"""图片和扫描 PDF 共用本地 Tesseract 配置。"""
import sys
import shutil
import tempfile
from pathlib import Path

_data_cache = {}


def _compatible_tessdata(path):
    """部分 Windows Tesseract 构建不能读取中文目录，语言数据转存到临时目录。"""
    if sys.platform != "win32" or (str(path).isascii() and not any(c.isspace() for c in str(path))):
        return path
    key = str(path.resolve())
    if key not in _data_cache:
        cache = tempfile.TemporaryDirectory(prefix="invoice-ocr-")
        target = Path(cache.name)
        try:
            if any(c.isspace() for c in str(target)):
                import ctypes
                buffer = ctypes.create_unicode_buffer(32768)
                if ctypes.windll.kernel32.GetShortPathNameW(str(target), buffer, len(buffer)):
                    target = Path(buffer.value)
            if not str(target).isascii() or any(c.isspace() for c in str(target)):
                raise RuntimeError("OCR 引擎需要英文临时目录，请将 Windows TEMP/TMP 设置为可写的英文路径后重启软件。")
            for data in path.glob("*.traineddata"):
                shutil.copy2(data, target / data.name)
        except BaseException:
            cache.cleanup()
            raise
        _data_cache[key] = (cache, target)
    return _data_cache[key][1]


def prepare_ocr():
    import pytesseract

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    engine = base / "tesseract" / "tesseract.exe"
    tessdata = base / "tesseract" / "tessdata"
    config = ""
    if engine.is_file() and tessdata.is_dir():
        pytesseract.pytesseract.tesseract_cmd = str(engine)
        tessdata = _compatible_tessdata(tessdata)
        # pytesseract 在 Windows 上保留配置中的引号，使用无空格路径避免引号传入引擎。
        config = (f'--tessdata-dir {tessdata.as_posix()}' if sys.platform == "win32"
                  else f'--tessdata-dir "{tessdata}"')
    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError as error:
        raise RuntimeError("未找到 OCR 引擎。请使用内置 Tesseract 的官方便携版；源码运行请安装 Tesseract。") from error
    return config


def extract_text_from_image(path, language="chi_sim+eng"):
    """识别一张照片，校正 EXIF 方向并以白底处理透明区域。"""
    from PIL import Image, ImageOps
    import pytesseract

    if language not in {"chi_sim+eng", "chi_sim", "eng"}:
        raise ValueError("不支持的识别语言")
    config = prepare_ocr()
    available = set(pytesseract.get_languages(config=config))
    missing = set(language.split("+")) - available
    if missing:
        raise RuntimeError("OCR 缺少语言数据：" + "、".join(sorted(missing)) + "。请使用包含中文数据的官方便携版。")
    with Image.open(path) as source:
        if getattr(source, "n_frames", 1) > 1:
            raise ValueError("请选择单张图片；多帧图片请先拆帧")
        oriented = ImageOps.exif_transpose(source)
        try:
            with oriented.convert("RGBA") as rgba:
                with Image.new("RGB", rgba.size, "white") as background:
                    with rgba.getchannel("A") as alpha:
                        background.paste(rgba, mask=alpha)
                    with ImageOps.grayscale(background) as gray:
                        with ImageOps.autocontrast(gray) as prepared:
                            return pytesseract.image_to_string(
                                prepared, lang=language, config=config, timeout=120,
                            ).strip()
        finally:
            oriented.close()
