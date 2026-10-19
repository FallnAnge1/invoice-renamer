import tempfile
import unittest
from pathlib import Path

from invoice_app import build_filename, find_amount, find_invoice_date, find_invoice_number
from invoice_validation import validate_invoice, update_validation
from rename_preview import build_rename_plan, rename_no_replace


class InvoiceValidationTest(unittest.TestCase):
    def record(self, **changes):
        return dict({"buyer": "示例公司", "amount": "88.50", "date": "20261020",
                     "invoice_no": "000012345678", "status": "成功"}, **changes)

    def test_normalizes_valid_amount_dates_and_number(self):
        values, errors, _ = validate_invoice(self.record(amount="￥1,234.5", date="2026年10月20日", invoice_no="0000 1234 5678"))
        self.assertEqual(errors, {})
        self.assertEqual(values["amount"], "1234.50")
        self.assertEqual(values["date"], "20261020")
        self.assertEqual(values["invoice_no"], "000012345678")

    def test_accepts_negative_amount_without_changing_sign(self):
        values, errors, _ = validate_invoice(self.record(amount="-12.3"))
        self.assertFalse(errors)
        self.assertEqual(values["amount"], "-12.30")
        self.assertEqual(find_amount("价税合计 ￥-12.30"), "-12.30")

    def test_bad_amounts_are_blocked_without_rounding_or_guessing(self):
        for amount in ["NaN", "1e3", "1,23.45", "88.OO", "88.501", "", "Infinity", "--2"]:
            with self.subTest(amount=amount):
                _, errors, _ = validate_invoice(self.record(amount=amount))
                self.assertIn("amount", errors)
        self.assertEqual(find_amount("价税合计 ￥88.501"), "88.501")
        self.assertEqual(find_amount("价税合计 ￥88.OO"), "88.OO")

    def test_invalid_dates_and_numbers_are_not_partially_accepted(self):
        for date in ["20260229", "20261301", "202610200", "2026-1O-20"]:
            with self.subTest(date=date):
                _, errors, _ = validate_invoice(self.record(date=date))
                self.assertIn("date", errors)
                self.assertIsNone(find_invoice_date("开票日期：" + date))
        for number in ["1234567", "123456789012345678901", "12345678O", "12-345678", "12345678.1"]:
            _, errors, _ = validate_invoice(self.record(invoice_no=number))
            self.assertIn("invoice_no", errors)
            self.assertIsNone(find_invoice_number("发票号码：" + number))

    def test_missing_optional_fields_warn_but_do_not_block(self):
        _, errors, warnings = validate_invoice(self.record(date="", invoice_no=""))
        self.assertFalse(errors)
        self.assertEqual(set(warnings), {"date", "invoice_no"})

    def test_required_fields_and_control_characters_are_blocked(self):
        for buyer in ["", " / : ", "公司\x00"]:
            _, errors, _ = validate_invoice(self.record(buyer=buyer))
            self.assertIn("buyer", errors)

    def test_invalid_value_is_preserved_for_manual_correction(self):
        record = self.record(amount="88.OO")
        self.assertFalse(update_validation(record))
        self.assertEqual(record["amount"], "88.OO")
        self.assertEqual(record["status"], "失败")
        record["amount"] = "88.5"
        self.assertTrue(update_validation(record))
        self.assertEqual(record["amount"], "88.50")
        self.assertEqual(record["error"], "")


class RenamePlanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def record(self, name="原票.pdf", **changes):
        path = self.root / name
        path.write_bytes(b"source invoice")
        return dict({"path": str(path), "filename": name, "buyer": "示例公司", "amount": "88.50",
                     "date": "", "invoice_no": "", "status": "成功"}, **changes)

    def test_plan_is_read_only_and_matches_names_with_optional_omissions(self):
        record = self.record()
        before = dict(record)
        plan = build_rename_plan([record], build_filename)
        self.assertEqual(record, before)
        self.assertEqual(plan[0]["action"], "rename")
        self.assertEqual(Path(plan[0]["target"]).name, "示例公司_88.50.pdf")
        self.assertFalse(Path(plan[0]["target"]).exists())
        self.assertIn("缺少开票日期", plan[0]["reason"])

    def test_reserves_names_against_disk_and_other_batch_entries(self):
        records = [self.record("a.pdf"), self.record("b.pdf")]
        (self.root / "示例公司_88.50.pdf").write_bytes(b"existing")
        plan = build_rename_plan(records, build_filename)
        self.assertEqual([Path(row["target"]).name for row in plan],
                         ["示例公司_88.50_2.pdf", "示例公司_88.50_3.pdf"])
        self.assertTrue(all(row["conflict"] for row in plan))

    def test_skips_invalid_unprocessed_and_already_completed_records(self):
        records = [self.record("bad.pdf", amount="88.OO"), self.record("pending.pdf", status="待处理"),
                   self.record("done.pdf", status="已重命名")]
        plan = build_rename_plan(records, build_filename)
        self.assertTrue(all(row["action"] == "skip" for row in plan))
        self.assertIn("金额", plan[0]["reason"])
        self.assertIn("尚未识别", plan[1]["reason"])
        self.assertIn("已完成", plan[2]["reason"])

    def test_missing_file_and_duplicate_source_records_are_skipped(self):
        record = self.record()
        plan = build_rename_plan([record, dict(record)], build_filename)
        self.assertIn("重复", plan[1]["reason"])
        Path(record["path"]).unlink()
        self.assertEqual(build_rename_plan([record], build_filename)[0]["action"], "skip")

    def test_existing_correct_name_with_collision_suffix_is_noop(self):
        (self.root / "示例公司_88.50.pdf").touch()
        record = self.record("示例公司_88.50_2.pdf")
        row = build_rename_plan([record], build_filename)[0]
        self.assertEqual(row["action"], "skip")
        self.assertIn("无需修改", row["reason"])

    def test_no_replace_preserves_both_files_when_target_exists(self):
        source, target = self.root / "source.pdf", self.root / "target.pdf"
        source.write_bytes(b"source")
        target.write_bytes(b"keep target")
        with self.assertRaises(FileExistsError):
            rename_no_replace(source, target)
        self.assertEqual(source.read_bytes(), b"source")
        self.assertEqual(target.read_bytes(), b"keep target")


if __name__ == "__main__":
    unittest.main()
