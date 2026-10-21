"""显式调用的离线打包诊断，所有测试文件仅写入指定文件夹。"""
import json
import os
from pathlib import Path
import sys
import time
import traceback


def run_smoke_test(output_folder):
    folder = Path(output_folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    report = {"frozen": bool(getattr(sys, "frozen", False)), "checks": [], "passed": False}
    root = None
    try:
        from PIL import Image, ImageDraw, ImageFont
        import tkinter as tk
        from invoice_app import InvoiceApp, extract_text_via_ocr
        from converter_dialog import ConverterDialog
        from image_ocr_dialog import ImageOCRDialog
        from format_converter import convert_files
        from batch_ocr import export_separate, merge_results

        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        chinese_font = (fonts / "msyh.ttc").is_file()
        font = ImageFont.truetype(str(fonts / ("msyh.ttc" if chinese_font else "arial.ttf")), 48)
        report["chinese_sample"] = chinese_font
        photos = []
        for index in (1, 2):
            photo = folder / f"诊断照片 {index}.png"
            with Image.new("RGB", (1400, 360), "white") as image:
                draw = ImageDraw.Draw(image)
                draw.text((50, 50), "中文识别测试" if chinese_font else "OCR batch test", fill="black", font=font)
                draw.text((50, 150), f"Invoice 12345 Test {index}", fill="black", font=font)
                image.save(photo)
            photos.append(str(photo))
        broken = folder / "损坏照片.png"
        broken.write_bytes(b"not an image")
        blank = folder / "空白照片.png"
        with Image.new("RGB", (800, 400), "white") as image:
            image.save(blank)

        outputs, errors = convert_files(photos, "images_pdf", folder / "转换结果")
        assert not errors and len(outputs) == 1, (outputs, errors)
        pages, errors = convert_files(outputs, "pdf_png", folder / "转换结果")
        assert not errors and len(pages) == 2, (pages, errors)
        assert "12345" in extract_text_via_ocr(outputs[0]), "PDF OCR failed"
        report["checks"].append("images_pdf_pdf_png_scanned_pdf_ocr")

        root = tk.Tk()
        root.withdraw()
        app = InvoiceApp(root)
        from app_version import VERSION
        from app_paths import desktop_directory
        report["version"] = VERSION
        converter = app.open_converter()
        assert converter.window.winfo_toplevel() == root
        assert not converter.import_pdf.get()
        assert Path(converter.output.get()) == desktop_directory()
        ocr_page = app.open_image_ocr()
        assert ocr_page.window.winfo_toplevel() == root
        app.show_page("invoice")
        assert app.open_converter() is converter
        report["checks"].append("single_window_navigation_desktop_default_independent_conversion")
        root.update()
        converter.close()
        import clipboard_import
        original_grab = clipboard_import.ImageGrab.grabclipboard
        def sample_clipboard():
            with Image.open(photos[0]) as image:
                return image.copy()
        try:
            clipboard_import.ImageGrab.grabclipboard = sample_clipboard
            pasted_converter = ConverterDialog(app)
            pasted_converter.paste_clipboard()
            assert len(pasted_converter.paths) == 1
            temporary_photo = Path(pasted_converter.paths[0])
            converted, errors = convert_files(pasted_converter.paths, "image_pdf", folder / "剪贴板转换")
            assert not errors and len(converted) == 1
            pasted_converter.close()
            assert not temporary_photo.exists() and Path(converted[0]).exists()
            pasted_ocr = ImageOCRDialog(app)
            pasted_ocr.paste_clipboard()
            pasted_photo = Path(pasted_ocr.path)
            pasted_ocr.run()
            deadline = time.monotonic() + 130
            while pasted_ocr.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            assert not pasted_ocr.busy
            assert "12345" in pasted_ocr.records[0]["text"]
            pasted_ocr.saved_text = pasted_ocr.get_text()
            pasted_ocr.close()
            assert not pasted_photo.exists()
            report["checks"].append("clipboard_sample_import_conversion_real_ocr_cleanup")
        finally:
            clipboard_import.ImageGrab.grabclipboard = original_grab
        dialog = ImageOCRDialog(app)
        dialog.add_photos([photos[0], str(broken), str(blank), photos[1]])
        dialog.run()
        deadline = time.monotonic() + 150
        while dialog.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert not dialog.busy, "Batch OCR timed out"
        assert [r["status"] for r in dialog.records] == ["成功", "失败", "无文字", "成功"], dialog.records
        for record in (dialog.records[0], dialog.records[3]):
            assert "12345" in record["text"], record["text"]
            if chinese_font:
                assert any("\u4e00" <= c <= "\u9fff" for c in record["text"]), record["text"]
        exported, errors = export_separate(dialog.records, folder / "识别文字")
        assert not errors and len(exported) == 2, (exported, errors)
        (folder / "合并文字.txt").write_text(merge_results(dialog.records), encoding="utf-8")
        report["checks"].append("tk_main_converter_batch_ocr_good_broken_blank_export")
        report["statuses"] = [r["status"] for r in dialog.records]
        report["passed"] = True
    except BaseException:
        report["error"] = traceback.format_exc()
    finally:
        if root is not None:
            root.destroy()
        (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1
