import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from javcover.ui.canvas.items import DesignElementItem, RegionItem
from javcover.ui.canvas.scene import CoverScene
from javcover.ui.canvas.view import CoverView
from javcover.core.models import DesignElement, Guide, Project, Rect, Region
from javcover.services.image_ops import encode_png


class CanvasInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = Project(100, 80)
        self.view = CoverView()
        self.view.resize(600, 400)
        self.view.set_project(self.project)
        self.view.show()
        self.app.processEvents()
        self.view.fit_canvas()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.view.close()

    def viewport_point(self, x: int, y: int):
        return self.view.mapFromScene(QPointF(x, y))

    def drag(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        QTest.mousePress(
            self.view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=self.viewport_point(*start),
        )
        QTest.mouseMove(self.view.viewport(), self.viewport_point(*end), 10)
        QTest.mouseRelease(
            self.view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=self.viewport_point(*end),
        )
        self.app.processEvents()

    def test_drag_creates_region_in_source_pixel_coordinates(self) -> None:
        self.drag((20, 15), (72, 58))
        self.assertEqual(len(self.project.regions), 1)
        self.assertEqual(self.project.regions[0].rect, Rect(20, 15, 52, 43))

    def test_drag_moves_existing_region(self) -> None:
        region = self.project.add_region(Rect(20, 15, 40, 30))
        self.view.refresh_overlays()
        self.view.select_region(region.id)
        self.view.draw_mode = False
        self.drag((40, 30), (45, 34))
        self.assertEqual(region.rect, Rect(25, 19, 40, 30))

    def test_drag_resizes_corner_in_pixel_coordinates(self) -> None:
        region = self.project.add_region(Rect(20, 15, 40, 30))
        self.view.refresh_overlays()
        self.view.select_region(region.id)
        self.view.draw_mode = False
        self.drag((20, 15), (25, 20))
        self.assertEqual(region.rect, Rect(25, 20, 35, 25))

    def test_drag_resizes_side_handle_without_changing_other_axis(self) -> None:
        region = self.project.add_region(Rect(20, 15, 40, 30))
        self.view.refresh_overlays()
        self.view.select_region(region.id)
        self.view.draw_mode = False
        self.drag((60, 30), (70, 30))
        self.assertEqual(region.rect, Rect(20, 15, 50, 30))

    def test_right_mouse_drag_pans_the_canvas(self) -> None:
        self.view.scale(2, 2)
        self.app.processEvents()
        horizontal = self.view.horizontalScrollBar()
        vertical = self.view.verticalScrollBar()
        horizontal.setValue(horizontal.maximum() // 2)
        vertical.setValue(vertical.maximum() // 2)
        before = (horizontal.value(), vertical.value())
        start = self.view.viewport().rect().center()
        end = start + QPointF(25, 20).toPoint()
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.RightButton, pos=start)
        QTest.mouseMove(self.view.viewport(), end, 10)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.RightButton, pos=end)
        self.assertNotEqual((horizontal.value(), vertical.value()), before)

    def test_right_mouse_interrupt_cancels_region_preview(self) -> None:
        start = self.viewport_point(20, 15)
        end = self.viewport_point(72, 58)
        QTest.mousePress(self.view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.view.viewport(), end, 10)
        self.assertIsNotNone(self.view._preview)

        QTest.mousePress(self.view.viewport(), Qt.MouseButton.RightButton, pos=end)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.RightButton, pos=end)
        QTest.mouseRelease(self.view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()

        self.assertIsNone(self.view._preview)
        self.assertIsNone(self.view._drag_kind)
        self.assertEqual(self.project.regions, [])

    def test_image_element_can_be_moved_and_resized_on_canvas(self) -> None:
        image = QImage(20, 15, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ff00ff"))
        element = DesignElement(
            kind="image",
            x=20,
            y=15,
            width=20,
            height=15,
            name="logo",
            png=encode_png(image),
        )
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self.drag((30, 22), (35, 26))
        self.assertEqual(element.rect, Rect(25, 19, 20, 15))
        self.drag((45, 26), (50, 26))
        self.assertEqual(element.rect, Rect(25, 19, 25, 15))

    def test_new_region_snaps_to_reference_line(self) -> None:
        self.project.guides.append(Guide("x", 68))
        self.view.refresh_overlays()
        self.drag((29, 20), (70, 60))
        self.assertEqual(self.project.regions[0].rect, Rect(27, 20, 41, 40))

    def test_new_region_is_cropped_at_canvas_edges_during_drag(self) -> None:
        self.drag((20, 15), (110, 90))
        self.assertEqual(self.project.regions[0].rect, Rect(20, 15, 80, 65))

    def test_reverse_drag_is_cropped_at_top_left_canvas_edges(self) -> None:
        self.drag((90, 70), (-10, -10))
        self.assertEqual(self.project.regions[0].rect, Rect(0, 0, 90, 70))

    def test_grid_snapping_works_without_regular_snapping(self) -> None:
        self.view.snapping = False
        self.view.grid_snapping = True
        self.view.grid_size = 100
        self.view.grid_subdivisions = 4
        self.drag((28, 20), (73, 60))
        region = self.project.regions[0].rect
        self.assertEqual(region, Rect(28, 20, 45, 40))
        self.assertEqual(region.center_x % 25, 0)

    def test_guide_can_be_dragged_on_canvas(self) -> None:
        self.project.guides.append(Guide("x", 30))
        self.view.refresh_overlays()
        self.drag((30, 20), (45, 20))
        self.assertEqual(self.project.guides[0], Guide("x", 45))

    def test_refresh_overlays_does_not_duplicate_element_items(self) -> None:
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ff00ff"))
        self.project.elements.append(
            DesignElement(
                kind="image",
                x=10,
                y=10,
                width=10,
                height=10,
                name="logo",
                png=encode_png(image),
            )
        )
        self.view.refresh_overlays()
        for _ in range(5):
            self.view.refresh_overlays()
        items = [
            item
            for item in self.view.cover_scene.items()
            if isinstance(item, DesignElementItem)
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(len(self.view.element_items), 1)

    def test_set_project_clears_element_selection(self) -> None:
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ff00ff"))
        element = DesignElement(
            kind="image",
            x=10,
            y=10,
            width=10,
            height=10,
            name="logo",
            png=encode_png(image),
        )
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self.assertEqual(self.view.selected_element_id, element.id)
        self.view.set_project(Project(50, 50))
        self.assertIsNone(self.view.selected_element_id)

    def test_text_preview_renders_outline(self) -> None:
        element = DesignElement(
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
        item = DesignElementItem(element)
        image = QImage(120, 60, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        greens = [
            (x, y)
            for x in range(120)
            for y in range(60)
            if image.pixelColor(x, y).green() > 150 and image.pixelColor(x, y).red() < 100
        ]
        self.assertTrue(greens)

    def test_shift_corner_resize_preserves_aspect_ratio(self) -> None:
        region = self.project.add_region(Rect(20, 15, 40, 30))
        self.view.refresh_overlays()
        self.view.select_region(region.id)
        self.view._original_rect = Rect(20, 15, 40, 30)
        self.view._resize_corner = "se"
        self.view._shift_down = True
        result = self.view._resize_rect(QPointF(100, 100))
        self.assertAlmostEqual(result.width / result.height, 40 / 30, places=1)

    def test_region_label_only_drawn_when_selected(self) -> None:
        item = RegionItem(Region(rect=Rect(0, 0, 200, 100), name="色块候选 1"), None)

        def render() -> QImage:
            image = QImage(220, 120, QImage.Format.Format_ARGB32)
            image.fill(QColor(0, 0, 0, 0))
            painter = QPainter(image)
            item.paint(painter, None)
            painter.end()
            return image

        def bright_pixels(image: QImage) -> int:
            return sum(
                1
                for x in range(image.width())
                for y in range(image.height())
                if image.pixelColor(x, y).lightness() > 200
            )

        unselected = bright_pixels(render())
        item.selected = True
        selected = bright_pixels(render())
        self.assertGreater(selected, unselected)

    def test_small_region_label_does_not_overflow_bounds(self) -> None:
        item = RegionItem(Region(rect=Rect(0, 0, 20, 12), name="色块候选 1"), None)
        image = QImage(60, 40, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        overflow = [
            (x, y)
            for x in range(60)
            for y in range(40)
            if not (-3 <= x <= 23 and -3 <= y <= 15)
            and image.pixelColor(x, y).alpha() > 0
        ]
        self.assertEqual(overflow, [])

    def test_linked_layer_is_clamped_to_region(self) -> None:
        region = self.project.add_region(Rect(20, 10, 40, 40))
        element = DesignElement(
            kind="text",
            x=20,
            y=10,
            width=20,
            height=20,
            name="t",
            text="A",
            region_id=region.id,
        )
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self.view.draw_mode = False
        self.drag((30, 20), (95, 75))
        self.assertGreaterEqual(element.x, region.rect.x)
        self.assertGreaterEqual(element.y, region.rect.y)
        self.assertLessEqual(element.x + element.width, region.rect.right)
        self.assertLessEqual(element.y + element.height, region.rect.bottom)

    def test_moving_region_reclamps_linked_layer(self) -> None:
        region = self.project.add_region(Rect(20, 10, 40, 40))
        element = DesignElement(
            kind="text",
            x=50,
            y=40,
            width=20,
            height=20,
            name="t",
            text="A",
            region_id=region.id,
        )
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.select_region(region.id)
        self.view._original_rect = region.rect
        self.view._set_selected_rect(Rect(0, 0, 30, 30))
        self.assertGreaterEqual(element.x, 0)
        self.assertLessEqual(element.x + element.width, 30)

    def test_align_rect_snaps_center_to_canvas_center(self) -> None:
        element = DesignElement(
            kind="text", x=39, y=29, width=20, height=20, name="t", text="A"
        )
        self.project.elements.append(element)
        self.view.snapping = True
        rect, guides = self.view._align_rect(element.rect, None, element.id)
        self.assertEqual(rect.center_x, 50)
        self.assertEqual(rect.center_y, 40)
        self.assertIn("x", [axis for axis, _ in guides])
        self.assertIn("y", [axis for axis, _ in guides])

    def test_crop_element_reduces_image_and_rect(self) -> None:
        from javcover.services.image_ops import decode_png

        image = QImage(40, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor("#336699"))
        element = DesignElement(
            kind="image",
            x=10,
            y=10,
            width=40,
            height=20,
            name="e",
            png=encode_png(image),
        )
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view._crop_target = ("element", element.id)
        self.view._apply_crop(QRectF(20, 15, 10, 10))
        self.assertEqual(element.rect, Rect(20, 15, 10, 10))
        self.assertEqual(decode_png(element.png).width(), 10)
        self.assertEqual(decode_png(element.png).height(), 10)

    def test_crop_overlay_geometry(self) -> None:
        from javcover.ui.canvas.crop import CropOverlay

        overlay = CropOverlay(QRectF(0, 0, 100, 100), grid_size=50, grid_subdivisions=5)
        self.assertEqual(overlay.handle_at(QPointF(0, 0), 5), "nw")
        self.assertIsNone(overlay.handle_at(QPointF(50, 50), 5))
        self.assertTrue(overlay.contains(QPointF(50, 50)))
        clamped = overlay.clamped(QRectF(10, 10, 100, 100).translated(QPointF(50, 50)))
        self.assertEqual(clamped, QRectF(0, 0, 100, 100))
        resized = overlay.resized(
            QRectF(10, 10, 40, 20), "se", QPointF(100, 100), keep_aspect=True
        )
        self.assertAlmostEqual(resized.width() / resized.height(), 2.0, places=1)

    def test_canvas_crop_apply_and_cancel_flow(self) -> None:
        image = QImage(40, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor("#336699"))
        element = DesignElement(
            kind="image",
            x=10,
            y=10,
            width=40,
            height=20,
            name="e",
            png=encode_png(image),
        )
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.crop_mode = True
        self.assertTrue(self.view.start_crop_at(QPointF(30, 20)))
        self.assertIsNotNone(self.view.crop_overlay)
        self.view.crop_overlay.set_crop(QRectF(20, 15, 10, 10))
        # Preview only: no document change until apply.
        self.assertEqual(element.rect, Rect(10, 10, 40, 20))
        self.view.cancel_crop()
        self.assertIsNone(self.view.crop_overlay)
        self.assertEqual(element.rect, Rect(10, 10, 40, 20))

        self.assertTrue(self.view.start_crop_at(QPointF(30, 20)))
        self.view.crop_overlay.set_crop(QRectF(20, 15, 10, 10))
        self.view.apply_crop()
        self.assertIsNone(self.view.crop_overlay)
        self.assertEqual(element.rect, Rect(20, 15, 10, 10))

    def test_grid_is_rendered_above_base_image(self) -> None:
        scene = CoverScene()
        scene.canvas_width = 100
        scene.canvas_height = 80
        scene.grid_visible = True
        scene.grid_size = 20
        scene.grid_subdivisions = 4
        image = QImage(100, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#777777"))
        scene.addPixmap(QPixmap.fromImage(image))
        scene.setSceneRect(0, 0, 100, 80)
        output = QImage(100, 80, QImage.Format.Format_ARGB32)
        output.fill(QColor("#000000"))
        painter = QPainter(output)
        scene.render(painter, QRectF(0, 0, 100, 80), QRectF(0, 0, 100, 80))
        painter.end()
        self.assertNotEqual(output.pixelColor(5, 25), QColor("#777777"))


if __name__ == "__main__":
    unittest.main()
