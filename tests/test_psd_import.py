import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace

from javcover.psd_import import (
    PsdImportError,
    _text_style,
    import_psd,
    import_psd_overlay,
    rasterize_psd,
)
from javcover.image_ops import compose_project, decode_png, encode_png
from javcover.models import Project
from PySide6.QtGui import QColor, QImage


@unittest.skipIf(find_spec("psd_tools") is None, "optional psd-tools dependency is not installed")
class PsdImportTests(unittest.TestCase):
    def test_extracts_replaceable_text_layer_style(self) -> None:
        from psd_tools.api.typesetting import WritingDirection

        style = SimpleNamespace(
            font=SimpleNamespace(
                family="Example Gothic",
                postscript_name="ExampleGothic-Bold",
                style="Bold Italic",
            ),
            font_name="ExampleGothic-Bold",
            font_size=24.0,
            fill_color=(1.0, 0.2, 0.4, 0.6),
            stroke_color=(1.0, 0.0, 0.0, 0.0),
            stroke_flag=True,
            faux_bold=False,
            faux_italic=False,
        )
        layer = SimpleNamespace(
            typesetting=SimpleNamespace(
                runs=[SimpleNamespace(style=style)],
                writing_direction=WritingDirection.HORIZONTAL_TB,
            )
        )
        self.assertEqual(
            _text_style(layer),
            {
                "font_family": "Example Gothic",
                "font_size": 32,
                "color": "#336699",
                "outline_color": "#000000",
                "outline_width": 2,
                "bold": True,
                "italic": True,
                "vertical": False,
            },
        )

    def test_imports_composite_as_a_project_background(self) -> None:
        from psd_tools import PSDImage

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.psd"
            PSDImage.new("RGB", (32, 24), color=(12, 34, 56)).save(path)
            project = import_psd(path)
        self.assertEqual((project.width, project.height), (32, 24))
        self.assertTrue(project.base_png)
        self.assertEqual(project.elements, [])

    def test_imports_transparent_psd_composite_as_image_overlay(self) -> None:
        from psd_tools import PSDImage

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "title-art.psd"
            PSDImage.new("RGBA", (32, 24), color=(25, 35, 45, 128)).save(path)
            element = import_psd_overlay(path)

        self.assertEqual((element.x, element.y), (0, 0))
        self.assertEqual((element.width, element.height), (32, 24))
        self.assertEqual(element.kind, "image")
        self.assertEqual(decode_png(element.png).pixelColor(10, 10).alpha(), 128)
        background = QImage(32, 24, QImage.Format.Format_ARGB32)
        background.fill(QColor("#ffffff"))
        project = Project(32, 24, base_png=encode_png(background), elements=[element])
        exported = compose_project(project)
        self.assertEqual(exported.pixelColor(10, 10).alpha(), 255)
        self.assertNotEqual(exported.pixelColor(10, 10), QColor("#ffffff"))

    def test_rejects_opaque_psd_as_an_overlay(self) -> None:
        from psd_tools import PSDImage

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "opaque.psd"
            PSDImage.new("RGB", (32, 24), color=(255, 255, 255)).save(path)
            with self.assertRaisesRegex(PsdImportError, "没有透明区域"):
                import_psd_overlay(path)

    def test_rasterize_psd_accepts_opaque_and_arbitrary_size(self) -> None:
        from psd_tools import PSDImage

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "title.psd"
            PSDImage.new("RGB", (40, 20), color=(120, 30, 200)).save(path)
            image = rasterize_psd(path)
        self.assertEqual((image.width(), image.height()), (40, 20))
        self.assertGreater(image.pixelColor(20, 10).blue(), 150)


if __name__ == "__main__":
    unittest.main()
