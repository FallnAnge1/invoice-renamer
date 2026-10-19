"""本地文件转换；所有输出独占创建，绝不覆盖已有文件。"""
from pathlib import Path
from PIL import Image, ImageOps

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
MODES = {
    "图片转 PDF（每图一份）": "image_pdf",
    "多图合并为 PDF": "images_pdf",
    "PDF 转 PNG 图片": "pdf_png",
    "PDF 转 JPG 图片": "pdf_jpg",
    "图片转 JPG": "image_jpg",
    "图片转 PNG": "image_png",
    "图片转 WebP": "image_webp",
    "图片转 BMP": "image_bmp",
    "合并 PDF": "merge_pdf",
    "拆分 PDF（每页一份）": "split_pdf",
}


def _write_output(folder, stem, suffix, writer):
    """排除已有路径，失败时移除本次未完成的输出。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for number in range(1, 10000):
        path = folder / f"{stem}{'' if number == 1 else '_' + str(number)}{suffix}"
        try:
            stream = path.open("xb")
        except FileExistsError:
            continue
        try:
            with stream:
                writer(stream)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return str(path)
    raise ValueError("同名文件过多，请更换输出文件夹")


def _load_image(path):
    with Image.open(path) as source:
        if getattr(source, "n_frames", 1) > 1:
            raise ValueError("多帧图片请先拆为单张图片，以免遗漏页面")
        return ImageOps.exif_transpose(source).copy()


def _rgb(image):
    """透明区域以白色填充，避免 JPG/PDF 出现黑底。"""
    rgba = image.convert("RGBA")
    try:
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    finally:
        rgba.close()


def convert_files(paths, mode, output_dir, progress=None):
    """按列表顺序转换，返回 (成功输出路径, 失败说明)。合并遇错不产出残缺文档。"""
    paths = [Path(path) for path in paths]
    if mode not in MODES.values():
        raise ValueError("不支持的转换方式")
    if not paths:
        raise ValueError("请先添加文件")
    image_mode = mode.startswith("image")
    for path in paths:
        if path.suffix.lower() not in (IMAGE_SUFFIXES if image_mode else {".pdf"}):
            raise ValueError(f"所选转换方式不支持：{path.name}")
    outputs, failures = [], []

    if mode == "images_pdf":
        images = []
        try:
            for index, path in enumerate(paths):
                with _load_image(path) as image:
                    images.append(_rgb(image))
                if progress:
                    progress(index + 1, len(paths))
            outputs.append(_write_output(output_dir, "合并图片", ".pdf", lambda stream:
                images[0].save(stream, format="PDF", save_all=True,
                               append_images=images[1:], resolution=150.0)))
        finally:
            for image in images:
                image.close()
        return outputs, failures

    if mode == "merge_pdf":
        import pypdfium2 as pdfium
        with pdfium.PdfDocument.new() as merged:
            for index, path in enumerate(paths):
                with pdfium.PdfDocument(path) as document:
                    merged.import_pages(document)
                if progress:
                    progress(index + 1, len(paths))
            outputs.append(_write_output(output_dir, "合并文档", ".pdf", merged.save))
        return outputs, failures

    for index, path in enumerate(paths):
        try:
            if image_mode:
                suffix = ".pdf" if mode == "image_pdf" else "." + mode.split("_")[1]
                image_format = {".jpg": "JPEG", ".png": "PNG", ".webp": "WEBP",
                                ".bmp": "BMP", ".pdf": "PDF"}[suffix]
                with _load_image(path) as source:
                    converted = _rgb(source) if suffix in {".jpg", ".pdf", ".bmp"} else source.copy()
                    with converted:
                        options = {"quality": 95} if suffix in {".jpg", ".webp"} else {}
                        if suffix == ".pdf":
                            options["resolution"] = 150.0
                        outputs.append(_write_output(output_dir, path.stem, suffix, lambda stream:
                            converted.save(stream, format=image_format, **options)))
            else:
                import pypdfium2 as pdfium
                with pdfium.PdfDocument(path) as document:
                    for page_index in range(len(document)):
                        stem = f"{path.stem}_第{page_index + 1:03d}页"
                        if mode == "split_pdf":
                            with pdfium.PdfDocument.new() as single:
                                single.import_pages(document, pages=[page_index])
                                outputs.append(_write_output(output_dir, stem, ".pdf", single.save))
                        else:
                            page = document[page_index]
                            try:
                                # 150 DPI；逐页释放内存，不把整份 PDF 的图片堆在内存中。
                                bitmap = page.render(scale=150 / 72)
                                try:
                                    with bitmap.to_pil() as image:
                                        suffix = ".png" if mode == "pdf_png" else ".jpg"
                                        with _rgb(image) as rgb:
                                            outputs.append(_write_output(output_dir, stem, suffix,
                                                lambda stream: rgb.save(stream,
                                                    format="PNG" if suffix == ".png" else "JPEG")))
                                finally:
                                    bitmap.close()
                            finally:
                                page.close()
        except Exception as error:
            failures.append(f"{path.name}: {error}")
        if progress:
            progress(index + 1, len(paths))
    return outputs, failures
