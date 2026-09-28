import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from javcover.image_ops import compose_project, encode_png
from javcover.models import DesignElement, Project, Rect, Region


def solid_png(width: int, height: int, color: QColor) -> bytes:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(color)
    return encode_png(image)


class ImageCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_region_background_is_cropped_into_region(self) -> None:
        project = Project(
            width=8,
            height=8,
            base_png=solid_png(8, 8, QColor("#0000ff")),
            regions=[
                Region(
                    rect=Rect(2, 2, 4, 4),
                    name="front",
                    background_png=solid_png(4, 4, QColor("#ff0000")),
                )
            ],
        )
        result = compose_project(project)
        self.assertEqual(result.size(), QImage(8, 8, QImage.Format.Format_ARGB32).size())
        self.assertEqual(result.pixelColor(0, 0), QColor("#0000ff"))
        self.assertEqual(result.pixelColor(3, 3), QColor("#ff0000"))

    def test_hidden_region_background_is_not_exported(self) -> None:
        project = Project(
            width=8,
            height=8,
            base_png=solid_png(8, 8, QColor("#0000ff")),
            regions=[
                Region(
                    rect=Rect(2, 2, 4, 4),
                    name="hidden",
                    background_png=solid_png(4, 4, QColor("#ff0000")),
                    visible=False,
                )
            ],
        )
        result = compose_project(project)
        self.assertEqual(result.pixelColor(3, 3), QColor("#0000ff"))

    def test_region_contain_letterboxes_and_stretch_fills(self) -> None:
        background = solid_png(4, 8, QColor("#ff0000"))
        base = solid_png(8, 8, QColor("#0000ff"))
        contained = compose_project(
            Project(
                width=8,
                height=8,
                base_png=base,
                regions=[
                    Region(rect=Rect(0, 0, 8, 8), name="r", background_png=background, fit="contain")
                ],
            )
        )
        self.assertEqual(contained.pixelColor(0, 0), QColor("#0000ff"))
        self.assertEqual(contained.pixelColor(4, 4), QColor("#ff0000"))
        stretched = compose_project(
            Project(
                width=8,
                height=8,
                base_png=base,
                regions=[
                    Region(rect=Rect(0, 0, 8, 8), name="r", background_png=background, fit="stretch")
                ],
            )
        )
        self.assertEqual(stretched.pixelColor(0, 0), QColor("#ff0000"))

    def test_region_opacity_blends_background(self) -> None:
        project = Project(
            width=4,
            height=4,
            base_png=solid_png(4, 4, QColor("#000000")),
            regions=[
                Region(
                    rect=Rect(0, 0, 4, 4),
                    name="r",
                    background_png=solid_png(4, 4, QColor("#ffffff")),
                    opacity=50,
                )
            ],
        )
        result = compose_project(project)
        value = result.pixelColor(2, 2).red()
        self.assertTrue(100 < value < 160, value)

    def test_hidden_element_is_not_exported(self) -> None:
        project = Project(
            width=4,
            height=4,
            elements=[
                DesignElement(
                    kind="image",
                    x=0,
                    y=0,
                    width=4,
                    height=4,
                    name="hidden",
                    png=solid_png(4, 4, QColor("#ff0000")),
                    visible=False,
                )
            ],
        )
        result = compose_project(project)
        self.assertEqual(result.pixelColor(2, 2).alpha(), 0)

    def test_element_blend_mode_changes_result(self) -> None:
        base = solid_png(4, 4, QColor("#808080"))
        element_png = solid_png(4, 4, QColor("#808080"))

        def rendered(mode: str) -> int:
            project = Project(
                width=4,
                height=4,
                base_png=base,
                elements=[
                    DesignElement(
                        kind="image",
                        x=0,
                        y=0,
                        width=4,
                        height=4,
                        name="e",
                        png=element_png,
                        blend_mode=mode,
                    )
                ],
            )
            return compose_project(project).pixelColor(2, 2).red()

        normal = rendered("normal")
        multiplied = rendered("multiply")
        self.assertTrue(multiplied < normal - 20, (normal, multiplied))

    def test_image_element_is_composited_over_the_cover(self) -> None:
        project = Project(
            width=8,
            height=8,
            base_png=solid_png(8, 8, QColor("#0000ff")),
            elements=[
                DesignElement(
                    kind="image",
                    x=2,
                    y=2,
                    width=3,
                    height=3,
                    name="logo",
                    png=solid_png(3, 3, QColor("#ff0000")),
                )
            ],
        )
        result = compose_project(project)
        self.assertEqual(result.pixelColor(0, 0), QColor("#0000ff"))
        self.assertEqual(result.pixelColor(3, 3), QColor("#ff0000"))

    def test_text_element_renders_to_the_requested_color(self) -> None:
        project = Project(
            width=80,
            height=40,
            elements=[
                DesignElement(
                    kind="text",
                    x=5,
                    y=5,
                    width=70,
                    height=30,
                    name="title",
                    text="TEST",
                    font_size=18,
                    color="#ff0000",
                )
            ],
        )
        result = compose_project(project)
        self.assertTrue(
            any(
                result.pixelColor(x, y).red() > 200
                and result.pixelColor(x, y).green() < 30
                for x in range(result.width())
                for y in range(result.height())
            )
        )

    def test_text_element_exports_at_configured_font_size(self) -> None:
        project = Project(
            width=600,
            height=260,
            elements=[
                DesignElement(
                    kind="text",
                    x=0,
                    y=0,
                    width=600,
                    height=260,
                    name="title",
                    text="AB",
                    font_size=20,
                    color="#ff0000",
                )
            ],
        )
        result = compose_project(project)
        painted = [
            (x, y)
            for x in range(result.width())
            for y in range(result.height())
            if result.pixelColor(x, y).red() > 200
            and result.pixelColor(x, y).green() < 30
        ]
        self.assertTrue(painted)
        height = max(y for _x, y in painted) - min(y for _x, y in painted) + 1
        self.assertLessEqual(height, 60)

    def test_text_element_exports_outline(self) -> None:
        project = Project(
            width=120,
            height=60,
            elements=[
                DesignElement(
                    kind="text",
                    x=0,
                    y=0,
                    width=120,
                    height=60,
                    name="title",
                    text="I",
                    font_size=40,
                    color="#ff0000",
                    outline_color="#00ff00",
                    outline_width=3,
                )
            ],
        )
        result = compose_project(project)
        greens = [
            (x, y)
            for x in range(result.width())
            for y in range(result.height())
            if result.pixelColor(x, y).green() > 150
            and result.pixelColor(x, y).red() < 100
        ]
        self.assertTrue(greens)


if __name__ == "__main__":
    unittest.main()
