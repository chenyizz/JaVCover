import unittest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage, QPainter

from javcover.services.assist import (
    list_tesseract_languages,
    recognize_japanese_text,
    suggest_color_blocks,
)
from javcover.core.models import Rect


class AssistTests(unittest.TestCase):
    def test_color_block_assist_detects_a_strong_panel_seam(self) -> None:
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("#ff0000"))
        painter = QPainter(image)
        painter.fillRect(100, 0, 100, 100, QColor("#0000ff"))
        painter.end()
        self.assertEqual(
            suggest_color_blocks(image),
            [Rect(0, 0, 100, 100), Rect(100, 0, 100, 100)],
        )

    def test_color_block_assist_ignores_uniform_images(self) -> None:
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("#7f7f7f"))
        self.assertEqual(suggest_color_blocks(image), [])

    def test_missing_tesseract_reports_install_requirement(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        with patch("javcover.services.assist.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "tesseract.exe"):
                recognize_japanese_text(image)

    def test_language_listing_ignores_tesseract_header(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["tesseract"],
            returncode=0,
            stdout='List of available languages in "tessdata" (2):\neng\njpn\n',
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "tesseract.exe"
            executable.touch()
            with patch("javcover.services.assist.subprocess.run", return_value=completed):
                self.assertEqual(
                    list_tesseract_languages(str(executable)),
                    {"eng", "jpn"},
                )

    def test_missing_japanese_model_has_setup_instructions(self) -> None:
        image = QImage(8, 8, QImage.Format.Format_RGB32)
        with (
            patch("javcover.services.assist.resolve_tesseract", return_value="tesseract.exe"),
            patch("javcover.services.assist.list_tesseract_languages", return_value={"eng"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "jpn.traineddata"):
                recognize_japanese_text(image, tessdata_dir="C:\\ocr\\tessdata")


if __name__ == "__main__":
    unittest.main()
