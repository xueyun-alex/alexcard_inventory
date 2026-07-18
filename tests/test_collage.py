from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from core.collage import build_vertical_stock_export


class VerticalStockExportTests(unittest.TestCase):
    def test_builds_vertical_summary_with_all_items(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.png"
            second = root / "second.png"
            Image.new("RGB", (120, 180), "red").save(first)
            Image.new("RGB", (180, 120), "blue").save(second)
            output = root / "summary.png"

            result = build_vertical_stock_export(
                [
                    ("商品一", first, "裸卡", 1),
                    ("商品二", second, "带卡砖", 2),
                ],
                output,
            )

            self.assertEqual(result, (2, 0))
            self.assertTrue(output.is_file())
            with Image.open(output) as image:
                self.assertEqual(image.size, (720, 712))
                self.assertEqual(image.format, "PNG")

    def test_missing_image_does_not_create_partial_export(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            valid = root / "valid.png"
            Image.new("RGB", (100, 100), "green").save(valid)
            output = root / "summary.png"

            result = build_vertical_stock_export(
                [
                    ("存在", valid, "挂件袋", 1),
                    ("缺失", root / "missing.png", "裸卡", 1),
                ],
                output,
            )

            self.assertEqual(result, (0, 1))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
