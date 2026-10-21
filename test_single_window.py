import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from invoice_app import InvoiceApp
from app_paths import desktop_directory


class SingleWindowWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = InvoiceApp(self.root)
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.photo = self.folder / "测试图片.png"
        with Image.new("RGB", (600, 300), "white") as image:
            image.save(self.photo)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        if self.app._after_id:
            self.root.after_cancel(self.app._after_id)
        self.root.update_idletasks()
        self.root.destroy()

    def children(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self.children(child)

    def wait(self):
        deadline = time.monotonic() + 15
        while self.app.processing and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.root.update()
        self.assertFalse(self.app.processing)

    def test_tools_and_large_preview_share_one_toplevel(self):
        converter = self.app.open_converter()
        ocr = self.app.open_image_ocr()
        ocr.add_photos([self.photo])
        ocr.open_preview()
        self.root.update_idletasks()
        self.assertEqual(converter.window.winfo_toplevel(), self.root)
        self.assertEqual(ocr.window.winfo_toplevel(), self.root)
        self.assertEqual(ocr._image_viewer.winfo_toplevel(), self.root)
        self.assertFalse(any(isinstance(child, tk.Toplevel) for child in self.children(self.root)))
        self.assertEqual(ocr._image_viewer.winfo_manager(), "place")
        ocr._image_viewer.destroy()
        self.assertIsNone(ocr._image_viewer)
        self.assertEqual(len(ocr.records), 1)

    def test_navigation_reuses_pages_and_retains_text_order_and_files(self):
        converter = self.app.open_converter()
        converter.add_paths([str(self.photo)])
        converter.output.set(str(self.folder / "选择的输出目录"))
        ocr = self.app.open_image_ocr()
        ocr.add_photos([self.photo])
        ocr.complete("识别文字", None)
        ocr.result.insert("end", "人工修改")
        self.app.show_page("invoice")
        self.assertEqual(ocr.records[0]["text"], "识别文字人工修改")
        self.assertIs(self.app.open_converter(), converter)
        self.assertEqual(converter.paths, [str(self.photo)])
        self.assertEqual(Path(converter.output.get()), self.folder / "选择的输出目录")
        self.assertIs(self.app.open_image_ocr(), ocr)
        self.assertEqual(ocr.get_text(), "识别文字人工修改")
        visible = [w for w in self.app.workspace.winfo_children() if w.winfo_manager()]
        self.assertEqual(visible, [ocr.window])

    def test_conversion_remains_independent_after_navigation(self):
        converter = self.app.open_converter()
        converter.add_paths([str(self.photo)])
        converter.output.set(str(self.folder / "输出"))
        converter.run()
        self.wait()
        output = Path(converter.outputs[0])
        self.app.open_image_ocr()
        self.app.show_page("invoice")
        self.assertEqual(self.app.items, [])
        self.assertIs(self.app.open_converter(), converter)
        self.assertTrue(output.exists())
        self.assertEqual(converter.outputs, [str(output)])

    def test_processing_locks_navigation_and_unlocks_after_completion(self):
        converter = self.app.open_converter()
        self.app._set_processing(True)
        self.assertIsNone(self.app.open_image_ocr())
        self.assertEqual(self.app.current_page, "converter")
        self.assertFalse(self.app.invoice_button.instate(["!disabled"]))
        self.app._set_processing(False)
        self.assertIsNotNone(self.app.open_image_ocr())
        self.assertEqual(self.app.current_page, "ocr")

    def test_close_protects_unsaved_text_in_hidden_page(self):
        ocr = self.app.open_image_ocr()
        ocr.add_photos([self.photo])
        ocr.complete("未保存的重要文字", None)
        self.app.open_converter()
        with patch("image_ocr_dialog.messagebox.askyesno", return_value=False) as ask:
            self.app.close()
        ask.assert_called_once()
        self.assertTrue(self.root.winfo_exists())
        self.assertEqual(self.app.current_page, "ocr")
        self.assertEqual(ocr.get_text(), "未保存的重要文字")

    def test_clipboard_survives_page_switch_and_cleans_on_exit(self):
        ocr = self.app.open_image_ocr()
        with patch("clipboard_import.ImageGrab.grabclipboard", side_effect=lambda: Image.new("RGB", (80, 40))):
            ocr.paste_clipboard()
        photo = Path(ocr.path)
        self.app.open_converter()
        self.assertTrue(photo.exists())
        self.app.show_page("invoice")
        self.assertTrue(photo.exists())
        ocr.window.destroy()
        self.assertFalse(photo.exists())

    def test_page_shortcut_reaches_nested_widgets_but_keeps_text_paste(self):
        for page in (self.app.open_converter(), self.app.open_image_ocr()):
            self.assertIn(str(page.window), page.files.bindtags())
            self.assertTrue(page.window.bind("<Control-v>"))
            editor = getattr(page, "output_entry", None) or page.result
            with patch.object(page, "paste_clipboard") as paste:
                self.assertIsNone(page.paste_shortcut(SimpleNamespace(widget=editor)))
                self.assertEqual(page.paste_shortcut(SimpleNamespace(widget=page.files)), "break")
                paste.assert_called_once()

    def test_desktop_defaults_and_ocr_export_chooser_start_at_desktop(self):
        desktop = desktop_directory()
        converter = self.app.open_converter()
        self.assertEqual(Path(converter.output.get()), desktop)
        converter.add_paths([str(self.photo)])
        self.assertEqual(Path(converter.output.get()), desktop)
        ocr = self.app.open_image_ocr()
        ocr.add_photos([self.photo])
        ocr.complete("需要导出的文字", None)
        with patch("image_ocr_dialog.filedialog.asksaveasfilename", return_value="") as choose:
            ocr.save_text()
            self.assertEqual(Path(choose.call_args.kwargs["initialdir"]), desktop)
            ocr.export_merged()
            self.assertEqual(Path(choose.call_args.kwargs["initialdir"]), desktop)
        with patch("image_ocr_dialog.filedialog.askdirectory", return_value="") as choose:
            ocr.export_each()
            self.assertEqual(Path(choose.call_args.kwargs["initialdir"]), desktop)

    def test_compact_and_default_layout_keep_primary_controls_inside_main_window(self):
        self.root.attributes("-alpha", 0.0)
        self.root.deiconify()
        for size in ("1100x740", "1280x820"):
            self.root.geometry(size)
            for key in ("invoice", "converter", "ocr"):
                page = self.app.show_page(key)
                self.root.update()
                if key == "converter":
                    controls = [page.start, page.output_entry, page.add_button, page.paste_button,
                                page.remove_button, page.files]
                elif key == "ocr":
                    controls = [page.recognize_button, page.paste_button, page.export_button,
                                page.result, page.preview_stage, page.save_button, page.retry_button]
                    self.assertGreater(page.result.winfo_height(), 150)
                    self.assertGreater(page.preview_stage.winfo_height(), 80)
                else:
                    controls = [self.app.add_files_button, self.app.rename_button, self.app.tree]
                for control in controls:
                    with self.subTest(size=size, key=key, widget=str(control)):
                        self.assertTrue(control.winfo_ismapped())
                        x = control.winfo_rootx() - self.root.winfo_rootx()
                        y = control.winfo_rooty() - self.root.winfo_rooty()
                        self.assertGreaterEqual(x, 0)
                        self.assertGreaterEqual(y, 0)
                        self.assertLessEqual(x + control.winfo_width(), self.root.winfo_width())
                        self.assertLessEqual(y + control.winfo_height(), self.root.winfo_height())


if __name__ == "__main__":
    unittest.main()
