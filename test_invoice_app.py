import tempfile
import unittest
import zipfile
from pathlib import Path

from invoice_app import (
    _safe_archive_path,
    build_filename,
    find_amount,
    find_invoice_date,
    find_invoice_number,
    find_buyer_name,
    InvoiceApp,
    make_unique_path,
)


class InvoiceAppHelpersTest(unittest.TestCase):
    def test_extracts_common_invoice_fields(self):
        text = """购买方名称：上海示例科技有限公司
开票日期：2026年07月14日
发票号码：12345678901234567890
价税合计（小写）¥1,234.50
"""
        self.assertEqual(find_buyer_name(text), "上海示例科技有限公司")
        self.assertEqual(find_invoice_date(text), "20260714")
        self.assertEqual(find_invoice_number(text), "12345678901234567890")
        self.assertEqual(find_amount(text), "1234.50")

    def test_filename_uses_date_and_last_eight_invoice_digits(self):
        result = build_filename("上海/示例 公司", "1234.50", "20260714", "12345678901234567890")
        self.assertEqual(result, "20260714_上海示例公司_1234.50_34567890.pdf")

    def test_conflicting_filename_gets_sequence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "old.pdf"
            target = Path(temp_dir) / "new.pdf"
            source.touch()
            target.touch()
            self.assertEqual(make_unique_path(str(source), "new.pdf"), str(Path(temp_dir) / "new_2.pdf"))

    def test_archive_path_rejects_parent_directory_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                _safe_archive_path(temp_dir, "../outside.pdf")

    def test_zip_extraction_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../outside.pdf", "not a real PDF")
            with self.assertRaises(ValueError):
                InvoiceApp._extract_archive(object(), str(archive), str(Path(temp_dir) / "output"))


if __name__ == "__main__":
    unittest.main()
