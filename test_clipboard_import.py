import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from clipboard_import import ClipboardImport
from converter_dialog import ConverterDialog
from image_ocr_dialog import ImageOCRDialog
import test_ui_workflows as workflows


class ClipboardImportTest(unittest.TestCase):
    def setUp(self):
        self.reader = ClipboardImport()
        self.addCleanup(self.reader.cleanup)

    def test_images_keep_pixels_and_transparency_and_cleanup(self):
        with patch("clipboard_import.ImageGrab.grabclipboard", side_effect=lambda: Image.new("RGBA", (32, 24), (20, 80, 120, 100))):
            first = self.reader.read()[0]
            second = self.reader.read()[0]
        self.assertNotEqual(first, second)
        with Image.open(first) as image:
            self.assertEqual(image.getpixel((0, 0)), (20, 80, 120, 100))
        self.assertTrue(self.reader.is_temporary(first))
        self.reader.cleanup()
        self.assertFalse(Path(first).exists())
        self.assertFalse(Path(second).exists())

    def test_file_copy_accepts_supported_existing_paths_only_and_keeps_originals(self):
        with tempfile.TemporaryDirectory() as folder:
            photo, pdf, text = [Path(folder) / name for name in ("图片.png", "发票.pdf", "文本.txt")]
            for path in (photo, pdf, text):
                path.touch()
            with patch("clipboard_import.ImageGrab.grabclipboard", return_value=[str(photo), str(pdf), str(photo), str(text), folder]):
                self.assertEqual(self.reader.read(), [str(photo.resolve())])
                self.assertEqual(self.reader.read({".pdf"}), [str(pdf.resolve())])
            self.reader.cleanup()
            self.assertTrue(photo.exists())
            self.assertTrue(pdf.exists())

    def test_empty_text_and_url_clipboards_have_a_clear_error(self):
        for value in (None, [], "https://example.com/image.png"):
            with self.subTest(value=value), patch("clipboard_import.ImageGrab.grabclipboard", return_value=value):
                with self.assertRaisesRegex(ValueError, "没有当前功能支持"):
                    self.reader.read()

    def test_wrong_mode_does_not_create_temporary_image(self):
        with patch("clipboard_import.ImageGrab.grabclipboard", return_value=Image.new("RGB", (5, 5))):
            with self.assertRaisesRegex(ValueError, "图片转 PDF"):
                self.reader.read({".pdf"})
        self.assertIsNone(self.reader._temporary)

    def test_clipboard_read_failure_is_actionable(self):
        with patch("clipboard_import.ImageGrab.grabclipboard", side_effect=OSError("busy")):
            with self.assertRaisesRegex(ValueError, "重新复制"):
                self.reader.read()


# Reuse the real Tk setup without inheriting/rerunning the existing workflow tests.
class ClipboardWorkflowTest(unittest.TestCase):
    setUpClass = classmethod(workflows.DesktopWorkflowTest.setUpClass.__func__)
    tearDownClass = classmethod(workflows.DesktopWorkflowTest.tearDownClass.__func__)
    setUp = workflows.DesktopWorkflowTest.setUp
    shutdown = workflows.DesktopWorkflowTest.shutdown
    wait_for_worker = workflows.DesktopWorkflowTest.wait_for_worker

    def test_pasted_ocr_images_keep_edits_and_clean_up_on_window_destroy(self):
        dialog = ImageOCRDialog(self.app)
        with patch("clipboard_import.ImageGrab.grabclipboard", side_effect=lambda: Image.new("RGB", (80, 40), "white")):
            dialog.paste_clipboard()
            first = Path(dialog.path)
            dialog.complete("已有校对内容", None)
            dialog.result.insert("end", "人工修改")
            dialog.paste_clipboard()
        self.assertEqual(len(dialog.records), 2)
        self.assertEqual(dialog.records[0]["text"], "已有校对内容人工修改")
        with patch("image_ocr_dialog.messagebox.askyesno", return_value=False):
            dialog.close()
        self.assertTrue(first.exists())
        dialog.saved_text = dialog.get_text()
        dialog.close()
        self.assertFalse(first.exists())

    def test_pasted_conversion_uses_permanent_output_and_can_import_result(self):
        dialog = ConverterDialog(self.app)
        with patch("clipboard_import.ImageGrab.grabclipboard", side_effect=lambda: Image.new("RGB", (80, 40), "white")):
            dialog.paste_clipboard()
        photo = Path(dialog.paths[0])
        self.assertNotEqual(Path(dialog.output.get()).parent, photo.parent)
        dialog.output.set(str(self.folder / "保存结果"))
        dialog.run()
        self.wait_for_worker()
        self.assertEqual(len(dialog.outputs), 1)
        pdf = Path(dialog.outputs[0])
        dialog.close()
        self.assertFalse(photo.exists())
        self.assertTrue(pdf.is_file())
        self.assertEqual(Path(self.app.items[0]["path"]), pdf)

    def test_busy_dialogs_do_not_read_clipboard(self):
        for cls in (ConverterDialog, ImageOCRDialog):
            dialog = cls(self.app)
            dialog.busy = True
            with patch("clipboard_import.ImageGrab.grabclipboard") as read:
                dialog.paste_clipboard()
                read.assert_not_called()
            dialog.busy = False
            dialog.close()

    def test_text_paste_is_not_intercepted_and_list_paste_imports_image(self):
        for cls in (ConverterDialog, ImageOCRDialog):
            dialog = cls(self.app)
            editor = dialog.output_entry if cls is ConverterDialog else dialog.result
            with patch.object(dialog, "paste_clipboard") as paste:
                self.assertIsNone(dialog.paste_shortcut(SimpleNamespace(widget=editor)))
                paste.assert_not_called()
                self.assertEqual(dialog.paste_shortcut(SimpleNamespace(widget=dialog.files)), "break")
                paste.assert_called_once()
            dialog.close()

    def test_wrong_conversion_mode_shows_hint_without_adding_files(self):
        dialog = ConverterDialog(self.app)
        dialog.mode.set("合并 PDF")
        dialog.change_mode()
        with patch("clipboard_import.ImageGrab.grabclipboard", return_value=Image.new("RGB", (5, 5))), patch("converter_dialog.messagebox.showinfo") as info:
            dialog.paste_clipboard()
        self.assertFalse(dialog.paths)
        self.assertIn("图片转 PDF", info.call_args.args[1])
        dialog.close()


if __name__ == "__main__":
    unittest.main()
