import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from ocr_engine import extract_text_from_image, prepare_ocr


class ImageOCRTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "透明照片.png"
        with Image.new("RGBA", (60, 30), (0, 0, 0, 0)) as image:
            image.save(self.path)

    @patch("ocr_engine.prepare_ocr", return_value="")
    @patch("pytesseract.get_languages", return_value=["eng", "chi_sim"])
    def test_image_is_prepared_and_text_keeps_line_breaks(self, _languages, _config):
        def recognize(image, **kwargs):
            self.assertEqual(image.mode, "L")
            self.assertEqual(image.getpixel((0, 0)), 255)
            self.assertEqual(kwargs["lang"], "chi_sim+eng")
            self.assertEqual(kwargs["timeout"], 120)
            return "\n发票文字\nInvoice 123\n"
        with patch("pytesseract.image_to_string", side_effect=recognize):
            self.assertEqual(extract_text_from_image(self.path), "发票文字\nInvoice 123")

    @patch("ocr_engine.prepare_ocr", return_value="")
    @patch("pytesseract.get_languages", return_value=["eng"])
    def test_missing_chinese_data_is_actionable(self, _languages, _config):
        with self.assertRaisesRegex(RuntimeError, "chi_sim"):
            extract_text_from_image(self.path)

    @patch("ocr_engine.prepare_ocr", return_value="")
    @patch("pytesseract.get_languages", return_value=["eng"])
    @patch("pytesseract.image_to_string", return_value="English text")
    def test_english_only_does_not_require_chinese_data(self, recognize, _languages, _config):
        self.assertEqual(extract_text_from_image(self.path, "eng"), "English text")
        self.assertEqual(recognize.call_args.kwargs["lang"], "eng")

    def test_invalid_language_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_text_from_image(self.path, "invalid")

    @patch("ocr_engine.prepare_ocr", return_value="")
    @patch("pytesseract.get_languages", return_value=["eng", "chi_sim"])
    def test_corrupt_image_does_not_overwrite_source(self, _languages, _config):
        self.path.write_bytes(b"bad image")
        with self.assertRaises(Exception):
            extract_text_from_image(self.path)
        self.assertEqual(self.path.read_bytes(), b"bad image")

    @patch("ocr_engine.prepare_ocr", return_value="")
    @patch("pytesseract.get_languages", return_value=["eng", "chi_sim"])
    def test_exif_orientation_is_applied_before_ocr(self, _languages, _config):
        path = Path(self.temp.name) / "rotated.jpg"
        with Image.new("RGB", (80, 40), "white") as image:
            exif = image.getexif()
            exif[274] = 6
            image.save(path, exif=exif)
        def recognize(image, **_kwargs):
            self.assertEqual(image.size, (40, 80))
            return ""
        with patch("pytesseract.image_to_string", side_effect=recognize):
            self.assertEqual(extract_text_from_image(path), "")

    def test_missing_engine_has_readable_error(self):
        import pytesseract
        with patch("pytesseract.get_tesseract_version", side_effect=pytesseract.TesseractNotFoundError()):
            with self.assertRaisesRegex(RuntimeError, "未找到 OCR 引擎"):
                prepare_ocr()

    @unittest.skipUnless(sys.platform == "win32", "Windows 路径兼容性")
    def test_bundled_data_in_chinese_and_space_path_uses_safe_config(self):
        root = Path(self.temp.name) / "中文目录 with spaces"
        data = root / "tesseract" / "tessdata"
        data.mkdir(parents=True)
        (root / "tesseract" / "tesseract.exe").touch()
        (data / "chi_sim.traineddata").write_bytes(b"test language data")
        with patch.object(sys, "_MEIPASS", str(root), create=True), \
                patch("pytesseract.get_tesseract_version"), \
                patch("pytesseract.pytesseract.tesseract_cmd", "tesseract"):
            config = prepare_ocr()
            self.assertTrue(config.isascii())
            self.assertNotIn('"', config)
            self.assertEqual(config, prepare_ocr())
            copied = Path(config.split(" ", 1)[1]) / "chi_sim.traineddata"
            self.assertEqual(copied.read_bytes(), b"test language data")


if __name__ == "__main__":
    unittest.main()
