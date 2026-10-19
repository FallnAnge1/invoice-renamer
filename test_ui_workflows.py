"""验证真实 Tk 控件状态与文件流程；无显示环境自动跳过。"""
import tempfile
import time
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from invoice_app import InvoiceApp
from converter_dialog import ConverterDialog
from image_ocr_dialog import ImageOCRDialog
from rename_preview import build_rename_plan, RenamePreviewDialog
from invoice_app import build_filename


class DesktopWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as error:
            raise unittest.SkipTest(str(error))

    @classmethod
    def tearDownClass(cls):
        cls.root.update_idletasks()
        cls.root.destroy()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.app = InvoiceApp(self.root)
        self.root.withdraw()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.shutdown)
        self.pdf = self.folder / "发票.pdf"
        self.pdf.touch()
        self.photo = self.folder / "照片.png"
        with Image.new("RGB", (100, 50), "white") as image:
            image.save(self.photo)

    def shutdown(self):
        if self.app._after_id:
            self.root.after_cancel(self.app._after_id)
        self.root.update_idletasks()
        for widget in self.root.winfo_children():
            widget.destroy()

    def wait_for_worker(self):
        deadline = time.monotonic() + 10
        while self.app.processing and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.root.update()
        self.assertFalse(self.app.processing)

    def test_empty_list_actions_and_duplicate_import(self):
        self.assertEqual(str(self.app.rename_button["state"]), "disabled")
        self.assertEqual(str(self.app.preview_button["state"]), "disabled")
        self.assertTrue(self.app._insert_item(str(self.pdf)))
        self.assertFalse(self.app._insert_item(str(self.pdf)))
        self.assertFalse(self.app._insert_item(str(self.photo)))
        self.app._refresh_table()
        self.assertEqual(str(self.app.preview_button["state"]), "normal")
        self.assertEqual(self.app.stat_values[0]["text"], "1")

    def test_manual_correction_makes_failed_item_renameable(self):
        self.app._insert_item(str(self.pdf))
        self.app.items[0].update(status="失败", error="未识别")
        self.app._refresh_table()
        self.app._apply_edit(0, "buyer", "示例公司")
        self.assertEqual(self.app.items[0]["status"], "失败")
        self.app._apply_edit(0, "amount", "88.50")
        self.assertEqual(self.app.items[0]["status"], "成功")
        self.assertEqual(self.app.items[0]["error"], "")
        self.assertEqual(str(self.app.rename_button["state"]), "normal")
        self.app._apply_edit(0, "amount", "")
        self.assertEqual(self.app.items[0]["status"], "失败")
        self.assertEqual(str(self.app.rename_button["state"]), "normal")  # 仍可预览跳过原因

    def test_processing_blocks_actions_and_restores_them(self):
        self.app._insert_item(str(self.pdf))
        self.app._refresh_table()
        self.app._set_processing(True)
        self.assertEqual(str(self.app.preview_button["state"]), "disabled")
        self.assertEqual(str(self.app.convert_button["state"]), "disabled")
        self.app._set_processing(False)
        self.assertEqual(str(self.app.preview_button["state"]), "normal")
        self.assertEqual(str(self.app.rename_button["state"]), "normal")

    def test_real_rename_and_undo_preserve_contents(self):
        self.pdf.write_bytes(b"original invoice contents")
        self.app._insert_item(str(self.pdf))
        self.app.items[0].update(status="成功", buyer="示例公司", amount="88.50", date="20261020")
        self.app._refresh_table()
        with patch("invoice_app.messagebox.showinfo"):
            self.app._start_worker(self.app._run_rename)
            self.wait_for_worker()
            renamed = Path(self.app.items[0]["path"])
            self.assertEqual(renamed.name, "20261020_示例公司_88.50.pdf")
            self.assertFalse(self.pdf.exists())
            self.assertEqual(renamed.read_bytes(), b"original invoice contents")
            self.assertEqual(str(self.app.undo_button["state"]), "normal")
            self.app._start_worker(self.app._run_undo)
            self.wait_for_worker()
        self.assertTrue(self.pdf.exists())
        self.assertEqual(self.app.rename_history, [])
        self.assertEqual(str(self.app.undo_button["state"]), "disabled")

    def test_invalid_edit_is_marked_and_correction_restores_readiness(self):
        self.app._insert_item(str(self.pdf))
        self.app.items[0].update(buyer="示例公司", status="成功")
        self.app._apply_edit(0, "amount", "88.OO")
        self.assertEqual(self.app.items[0]["status"], "失败")
        self.assertIn("[异常]", self.app.tree.item("0", "values")[3])
        self.app._apply_edit(0, "amount", "88.5")
        self.assertEqual(self.app.items[0]["amount"], "88.50")
        self.assertEqual(self.app.items[0]["status"], "成功")

    def test_ocr_invalid_optional_date_is_blocked_instead_of_omitted(self):
        self.app._insert_item(str(self.pdf))
        text = "购买方名称：示例公司\n价税合计 ￥88.50\n开票日期：20260230\n发票号码：12345678O"
        with patch("invoice_app.extract_text_from_pdf", return_value=text):
            self.assertFalse(self.app._recognize_one(self.app.items[0]))
        self.assertIn("date", self.app.items[0]["validation_errors"])
        self.assertIn("invoice_no", self.app.items[0]["validation_errors"])

    def test_preview_cancel_keeps_files_and_confirm_uses_shown_target(self):
        self.app._insert_item(str(self.pdf))
        self.app.items[0].update(buyer="示例公司", amount="88.50", status="成功")
        plan = build_rename_plan(self.app.items, build_filename)
        dialog = RenamePreviewDialog(self.app, plan)
        self.assertTrue(self.pdf.exists())
        self.assertFalse(Path(plan[0]["target"]).exists())
        dialog.window.destroy()
        self.assertTrue(self.pdf.exists())
        dialog = RenamePreviewDialog(self.app, plan)
        with patch("invoice_app.messagebox.showinfo"):
            dialog.confirm_button.invoke()
            self.wait_for_worker()
        self.assertEqual(self.app.items[0]["path"], plan[0]["target"])
        self.assertFalse(self.pdf.exists())

    def test_all_invalid_preview_has_no_execution_button(self):
        self.app._insert_item(str(self.pdf))
        dialog = RenamePreviewDialog(self.app, build_rename_plan(self.app.items, build_filename))
        self.assertEqual(str(dialog.confirm_button["state"]), "disabled")
        dialog.confirm()
        self.assertFalse(self.app.processing)

    def test_new_conflict_after_preview_is_not_renamed_or_overwritten(self):
        self.app._insert_item(str(self.pdf))
        self.app.items[0].update(buyer="示例公司", amount="88.50", status="成功")
        plan = build_rename_plan(self.app.items, build_filename)
        target = Path(plan[0]["target"])
        target.write_bytes(b"newly occupied target")
        with patch("invoice_app.messagebox.showinfo"):
            self.app._start_worker(lambda: self.app._run_rename(plan))
            self.wait_for_worker()
        self.assertTrue(self.pdf.exists())
        self.assertEqual(target.read_bytes(), b"newly occupied target")
        self.assertIn("重新预览", self.app.items[0]["error"])
        self.assertEqual(self.app.rename_history, [])

    def test_source_change_after_preview_requires_review(self):
        self.app._insert_item(str(self.pdf))
        self.app.items[0].update(buyer="示例公司", amount="88.50", status="成功")
        plan = build_rename_plan(self.app.items, build_filename)
        self.pdf.write_bytes(b"changed source contents")
        with patch("invoice_app.messagebox.showinfo"):
            self.app._start_worker(lambda: self.app._run_rename(plan))
            self.wait_for_worker()
        self.assertTrue(self.pdf.exists())
        self.assertFalse(Path(plan[0]["target"]).exists())
        self.assertIn("源文件已改变", self.app.items[0]["error"])

    def test_folder_import_runs_in_background_and_skips_duplicates(self):
        with patch("invoice_app.filedialog.askdirectory", return_value=str(self.folder)):
            self.app.add_folder()
        self.wait_for_worker()
        self.assertEqual(len(self.app.items), 1)
        self.app._run_folder(self.folder)
        self.root.update()
        self.assertEqual(len(self.app.items), 1)

    def test_archive_import_runs_in_background_and_only_adds_pdfs(self):
        archive = self.folder / "发票包.zip"
        with zipfile.ZipFile(archive, "w") as files:
            files.writestr("nested/invoice.PDF", b"invoice contents")
            files.writestr("nested/readme.txt", b"not a PDF")
        with patch("invoice_app.Path.home", return_value=self.folder):
            self.app._start_worker(lambda: self.app._run_archives([str(archive)]))
            self.wait_for_worker()
        self.assertEqual(len(self.app.items), 1)
        self.assertEqual(Path(self.app.items[0]["path"]).read_bytes(), b"invoice contents")

    def test_remove_selected_keeps_disk_file(self):
        self.app._insert_item(str(self.pdf))
        self.app._refresh_table()
        self.app.tree.selection_set("0")
        self.app.remove_selected()
        self.assertEqual(self.app.items, [])
        self.assertTrue(self.pdf.exists())

    def test_failed_recheck_does_not_keep_old_fields(self):
        self.app._insert_item(str(self.pdf))
        item = self.app.items[0]
        item.update(buyer="上次公司", amount="99.00", date="20261020", invoice_no="12345678")
        with patch("invoice_app.extract_text_from_pdf", return_value="无法匹配到发票字段的足够长文字"):
            self.assertFalse(self.app._recognize_one(item))
        self.assertEqual(item["buyer"], "")
        self.assertEqual(item["amount"], "")
        self.assertEqual(item["date"], "")

    def test_recognition_preserves_already_corrected_items(self):
        self.app._insert_item(str(self.pdf))
        self.app.items[0].update(status="成功", buyer="已校对公司", amount="88.50")
        self.app._refresh_table()
        with patch.object(self.app, "_recognize_one") as recognize:
            self.app._run_preview()
            self.root.update()
        recognize.assert_not_called()
        self.assertEqual(self.app.items[0]["buyer"], "已校对公司")

    def test_converter_mode_preserves_compatible_files(self):
        dialog = ConverterDialog(self.app)
        dialog.paths = [str(self.photo)]
        dialog.mode.set("多图合并为 PDF")
        dialog.change_mode()
        self.assertEqual(dialog.paths, [str(self.photo)])
        dialog.mode.set("PDF 转 JPG 图片")
        dialog.change_mode()
        self.assertEqual(dialog.paths, [])
        self.assertTrue(self.photo.exists())
        self.assertEqual(str(dialog.start["state"]), "disabled")

    def test_converter_default_output_and_real_conversion_import(self):
        dialog = ConverterDialog(self.app)
        with patch("converter_dialog.filedialog.askopenfilenames", return_value=[str(self.photo)]):
            dialog.add_files()
        self.assertEqual(Path(dialog.output.get()), self.folder / "转换结果")
        self.assertEqual(str(dialog.start["state"]), "normal")
        dialog.run()
        self.wait_for_worker()
        self.assertEqual(len(self.app.items), 1)
        self.assertTrue(Path(self.app.items[0]["path"]).is_file())
        self.assertEqual(str(dialog.open_button["state"]), "normal")

    def test_ocr_empty_result_buttons_and_unsaved_protection(self):
        dialog = ImageOCRDialog(self.app)
        self.assertEqual(str(dialog.copy_button["state"]), "disabled")
        dialog.load_photo(self.photo)
        dialog.complete("需保留的识别文字", None)
        self.assertEqual(str(dialog.copy_button["state"]), "normal")
        with patch("image_ocr_dialog.messagebox.askyesno", return_value=False):
            dialog.load_photo(self.photo)
        self.assertEqual(dialog.result.get("1.0", "end-1c"), "需保留的识别文字")

    def test_ocr_failure_restores_controls_and_keeps_previous_text(self):
        dialog = ImageOCRDialog(self.app)
        dialog.load_photo(self.photo)
        dialog.complete("已复制的文字", None)
        dialog.saved_text = "已复制的文字"
        with patch("image_ocr_dialog.extract_text_from_image", side_effect=RuntimeError("引擎问题")):
            dialog.run()
            self.wait_for_worker()
        self.assertFalse(dialog.busy)
        self.assertEqual(str(dialog.recognize_button["state"]), "normal")
        self.assertEqual(dialog.result.get("1.0", "end-1c"), "已复制的文字")
        self.assertIn("引擎问题", dialog.status["text"])


if __name__ == "__main__":
    unittest.main()
