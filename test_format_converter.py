import tempfile
import unittest
from pathlib import Path

from PIL import Image
import pypdfium2 as pdfium

from format_converter import convert_files


class FormatConverterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "输出"
        self.red = self.root / "红色.png"
        self.blue = self.root / "蓝色.png"
        with Image.new("RGB", (120, 60), "red") as image:
            image.save(self.red)
        with Image.new("RGB", (60, 120), "blue") as image:
            image.save(self.blue)

    def convert(self, paths, mode):
        outputs, errors = convert_files(paths, mode, self.output)
        self.assertEqual(errors, [])
        return outputs

    def test_image_formats_preserve_size_and_transparency_or_use_white(self):
        transparent = self.root / "透明.png"
        with Image.new("RGBA", (30, 40), (255, 0, 0, 0)) as image:
            image.save(transparent)
        for mode in ["image_jpg", "image_png", "image_webp", "image_bmp"]:
            output = self.convert([transparent], mode)[0]
            with Image.open(output) as image:
                self.assertEqual(image.size, (30, 40))
                if mode in {"image_jpg", "image_bmp"}:
                    self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                else:
                    self.assertEqual(image.convert("RGBA").getpixel((0, 0))[3], 0)

    def test_images_pdf_page_order_and_aspect_ratio(self):
        output = self.convert([self.blue, self.red], "images_pdf")[0]
        with pdfium.PdfDocument(output) as doc:
            self.assertEqual(len(doc), 2)
            for index, expected in enumerate([(0, 0, 255), (255, 0, 0)]):
                page = doc[index]
                try:
                    width, height = page.get_size()
                    self.assertAlmostEqual(width / height, 0.5 if index == 0 else 2)
                    bitmap = page.render()
                    try:
                        with bitmap.to_pil() as image:
                            actual = image.convert("RGB").getpixel((10, 10))
                            for found, wanted in zip(actual, expected):
                                self.assertLess(abs(found - wanted), 5)
                    finally:
                        bitmap.close()
                finally:
                    page.close()

    def test_pdf_merge_split_and_render_round_trip(self):
        originals = self.convert([self.red, self.blue], "image_pdf")
        merged = self.convert(originals[::-1], "merge_pdf")[0]
        split = self.convert([merged], "split_pdf")
        self.assertEqual(len(split), 2)
        for path in split:
            with pdfium.PdfDocument(path) as doc:
                self.assertEqual(len(doc), 1)
        for mode in ["pdf_png", "pdf_jpg"]:
            outputs = self.convert([merged], mode)
            self.assertEqual(len(outputs), 2)
            with Image.open(outputs[0]) as image:
                self.assertLess(image.width, image.height)
                self.assertGreater(image.convert("RGB").getpixel((10, 10))[2], 240)

    def test_never_overwrites_input_or_existing_output(self):
        original = self.red.read_bytes()
        first, errors = convert_files([self.red], "image_png", self.root)
        self.assertEqual(errors, [])
        second, errors = convert_files([self.red], "image_png", self.root)
        self.assertEqual(errors, [])
        self.assertNotEqual(first, second)
        self.assertNotEqual(Path(first[0]), self.red)
        self.assertEqual(self.red.read_bytes(), original)

    def test_bad_batch_member_does_not_stop_good_files(self):
        broken = self.root / "损坏.png"
        broken.write_bytes(b"not an image")
        outputs, errors = convert_files([broken, self.red], "image_pdf", self.output)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn(broken.name, errors[0])

    def test_failed_merge_leaves_no_partial_pdf(self):
        broken = self.root / "损坏.png"
        broken.write_bytes(b"not an image")
        with self.assertRaises(Exception):
            convert_files([self.red, broken], "images_pdf", self.output)
        self.assertEqual(list(self.output.glob("*.pdf")), [])

    def test_exif_orientation_is_applied(self):
        source = self.root / "旋转.jpg"
        with Image.new("RGB", (80, 40), "red") as image:
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)
        output = self.convert([source], "image_png")[0]
        with Image.open(output) as image:
            self.assertEqual(image.size, (40, 80))

    def test_multiframe_image_is_reported_instead_of_losing_pages(self):
        source = self.root / "多页.tiff"
        with Image.new("RGB", (20, 20), "red") as first:
            with Image.new("RGB", (20, 20), "blue") as second:
                first.save(source, save_all=True, append_images=[second])
        outputs, errors = convert_files([source], "image_pdf", self.output)
        self.assertEqual(outputs, [])
        self.assertIn("多帧", errors[0])

    def test_wrong_file_type_rejected_before_output(self):
        with self.assertRaises(ValueError):
            convert_files([self.red], "pdf_png", self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
