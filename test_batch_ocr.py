import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from batch_ocr import new_record, merge_results, export_separate
from invoice_app import InvoiceApp
from image_ocr_dialog import ImageOCRDialog


class BatchTextExportTest(unittest.TestCase):
    def test_merged_results_keep_order_names_edits_and_failure_notes(self):
        records = [new_record("first.png"), new_record("empty.png"), new_record("third.png")]
        records[0].update(text="人工校对后的第一张", status="成功")
        records[2].update(text="保留的上次文字", status="失败", error="本次引擎失败")
        text = merge_results(records)
        self.assertLess(text.index("first.png"), text.index("third.png"))
        self.assertIn("人工校对后的第一张", text)
        self.assertNotIn("empty.png", text)
        self.assertIn("本次识别失败", text)
        self.assertIn("保留的上次文字", text)

    def test_separate_export_preserves_existing_files_and_same_stem_images(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / "同名.txt"
            existing.write_text("已有内容", encoding="utf-8")
            records = [new_record("a/同名.png"), new_record("b/同名.jpg"), new_record("empty.png")]
            records[0]["text"], records[1]["text"] = "中文第一份", "第二份"
            outputs, errors = export_separate(records, folder)
            self.assertFalse(errors)
            self.assertEqual([Path(path).name for _, path in outputs], ["同名_2.txt", "同名_3.txt"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "已有内容")
            self.assertEqual(Path(outputs[0][1]).read_text(encoding="utf-8"), "中文第一份")


class BatchOCRWorkflowTest(unittest.TestCase):
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
        self.dialog = ImageOCRDialog(self.app)
        self.photos = []
        for name in ("第一张.png", "第二张.png", "第三张.png"):
            path = self.folder / name
            with Image.new("RGB", (120, 60), "white") as image:
                image.save(path)
            self.photos.append(path)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.root.after_cancel(self.app._after_id)
        self.root.update_idletasks()
        for widget in self.root.winfo_children():
            widget.destroy()

    def wait(self):
        deadline = time.monotonic() + 15
        while self.app.processing and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.02)
        self.root.update()
        self.assertFalse(self.app.processing)
        self.assertFalse(self.dialog.busy)

    def select(self, index):
        self.dialog.files.selection_set(str(index))
        self.dialog.select_record()
        self.root.update()

    def test_multi_select_import_and_dedup_do_not_discard_existing_text(self):
        with patch("image_ocr_dialog.filedialog.askopenfilenames", return_value=[str(p) for p in self.photos]):
            self.dialog.choose_photo()
        self.assertEqual(len(self.dialog.records), 3)
        self.dialog.result.insert("1.0", "未保存的第一张修改")
        self.dialog.add_photos([self.photos[0]])
        self.assertEqual(len(self.dialog.records), 3)
        self.assertEqual(self.dialog.records[0]["text"], "未保存的第一张修改")

    def test_switching_records_preserves_edits_and_does_not_mix_text(self):
        self.dialog.add_photos(self.photos[:2])
        self.dialog.complete("第一张结果", None)
        self.dialog.result.insert("end", "人工补充")
        self.select(1)
        self.assertEqual(self.dialog.result.get("1.0", "end-1c"), "")
        self.dialog.complete("第二张结果", None)
        self.select(0)
        self.assertEqual(self.dialog.result.get("1.0", "end-1c"), "第一张结果人工补充")

    def test_batch_continues_after_failure_and_only_retries_failed_record(self):
        self.dialog.add_photos(self.photos)
        def recognize(path, _language):
            if Path(path) == self.photos[1]:
                raise RuntimeError("照片损坏")
            return "文字：" + Path(path).name
        with patch("image_ocr_dialog.extract_text_from_image", side_effect=recognize):
            self.dialog.run()
            self.wait()
        self.assertEqual([r["status"] for r in self.dialog.records], ["成功", "失败", "成功"])
        with patch("image_ocr_dialog.extract_text_from_image", return_value="第二张重试成功") as recognize:
            self.dialog.run_failed()
            self.wait()
        self.assertEqual(recognize.call_count, 1)
        self.assertEqual(self.dialog.records[1]["text"], "第二张重试成功")
        self.assertEqual(int(self.dialog.progress["value"]), 1)

    def test_batch_does_not_overwrite_manual_text_or_recognized_results(self):
        self.dialog.add_photos(self.photos)
        self.dialog.complete("已识别的第一张", None)
        self.select(1)
        self.dialog.result.insert("1.0", "人工填写第二张")
        with patch("image_ocr_dialog.extract_text_from_image", return_value="第三张结果") as recognize:
            self.dialog.run()
            self.wait()
        self.assertEqual(recognize.call_count, 1)
        self.assertEqual(self.dialog.records[0]["text"], "已识别的第一张")
        self.assertEqual(self.dialog.records[1]["text"], "人工填写第二张")
        self.assertEqual(self.dialog.records[2]["text"], "第三张结果")

    def test_current_result_stays_correct_when_view_changes_during_batch(self):
        self.dialog.add_photos(self.photos[:2])
        # 通过实际 UI 消息队列在任务开始后切换记录，结果仍按原索引写回。
        with patch("image_ocr_dialog.extract_text_from_image", side_effect=["第一张", "第二张"]):
            self.dialog.run()
            self.dialog.files.selection_set("1")
            self.dialog.select_record()
            self.wait()
        self.assertEqual(self.dialog.current_index, 1)
        self.assertEqual(self.dialog.result.get("1.0", "end-1c"), "第二张")
        self.assertEqual(self.dialog.records[0]["text"], "第一张")

    def test_empty_ocr_is_not_reported_as_success_and_is_not_exported(self):
        self.dialog.add_photos(self.photos[:1])
        with patch("image_ocr_dialog.extract_text_from_image", return_value=""):
            self.dialog.run()
            self.wait()
        self.assertEqual(self.dialog.records[0]["status"], "无文字")
        self.assertEqual(str(self.dialog.export_button["state"]), "disabled")
        self.dialog.store_current()
        self.assertEqual(self.dialog.records[0]["status"], "无文字")

    def test_reorder_and_exports_include_latest_edits_in_list_order(self):
        self.dialog.add_photos(self.photos[:2])
        self.dialog.complete("第一张文字", None)
        self.select(1)
        self.dialog.complete("第二张文字", None)
        self.dialog.result.insert("end", "校对")
        self.dialog.move(-1)
        output = self.folder / "合并.txt"
        with patch("image_ocr_dialog.filedialog.asksaveasfilename", return_value=str(output)):
            self.dialog.export_merged()
        text = output.read_text(encoding="utf-8")
        self.assertLess(text.index("第二张.png"), text.index("第一张.png"))
        self.assertIn("第二张文字校对", text)
        with patch("image_ocr_dialog.filedialog.askdirectory", return_value=str(self.folder / "每图TXT")):
            self.dialog.export_each()
        self.assertEqual((self.folder / "每图TXT" / "第二张.txt").read_text(encoding="utf-8"), "第二张文字校对")
        self.assertTrue(all(r["text"] == r["saved_text"] for r in self.dialog.records))

    def test_close_protects_unsaved_results_in_other_records(self):
        self.dialog.add_photos(self.photos[:2])
        self.dialog.complete("第一张未保存", None)
        self.select(1)
        with patch("image_ocr_dialog.messagebox.askyesno", return_value=False) as ask:
            self.dialog.close()
        ask.assert_called_once()
        self.assertTrue(self.dialog.window.winfo_exists())

    def test_explicit_rerecognition_cancel_preserves_manual_edits(self):
        self.dialog.add_photos(self.photos[:1])
        self.dialog.complete("人工校对内容", None)
        with patch("image_ocr_dialog.messagebox.askyesno", return_value=False), \
                patch("image_ocr_dialog.extract_text_from_image") as recognize:
            self.dialog.run_current()
        recognize.assert_not_called()
        self.assertEqual(self.dialog.records[0]["text"], "人工校对内容")

    def test_merged_export_cannot_overwrite_any_source_photo(self):
        self.dialog.add_photos(self.photos[:2])
        self.dialog.complete("第一张文字", None)
        before = self.photos[1].read_bytes()
        with patch("image_ocr_dialog.filedialog.asksaveasfilename", return_value=str(self.photos[1])), \
                patch("image_ocr_dialog.messagebox.showerror") as error:
            self.dialog.export_merged()
        error.assert_called_once()
        self.assertEqual(self.photos[1].read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
