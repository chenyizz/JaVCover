import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from javcover.app import CoverView
from javcover.canvas_widgets import RulerFrame
from javcover.models import Project


class RulerInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.view = CoverView()
        self.view.set_project(Project(100, 80))
        self.frame = RulerFrame(self.view)
        self.frame.resize(600, 420)
        self.frame.show()
        self.app.processEvents()
        self.view.fit_canvas()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.frame.close()

    def test_horizontal_ruler_drag_creates_vertical_guide(self) -> None:
        requested: list[tuple[str, int]] = []
        self.frame.guideRequested.connect(
            lambda axis, position: requested.append((axis, position))
        )
        ruler = self.frame.horizontal_ruler
        start_x = self.view.mapFromScene(QPointF(20, 0)).x()
        QTest.mousePress(
            ruler, Qt.MouseButton.LeftButton, pos=QPoint(start_x, 12)
        )
        viewport_position = self.view.mapFromScene(QPointF(35, 40))
        global_position = self.view.viewport().mapToGlobal(viewport_position)
        ruler_position = ruler.mapFromGlobal(global_position)
        QTest.mouseMove(ruler, ruler_position, 10)
        QTest.mouseRelease(
            ruler, Qt.MouseButton.LeftButton, pos=ruler_position
        )
        self.app.processEvents()
        self.assertEqual(requested, [("x", 35)])

    def test_vertical_ruler_drag_creates_horizontal_guide(self) -> None:
        requested: list[tuple[str, int]] = []
        self.frame.guideRequested.connect(
            lambda axis, position: requested.append((axis, position))
        )
        ruler = self.frame.vertical_ruler
        start_y = self.view.mapFromScene(QPointF(0, 20)).y()
        QTest.mousePress(
            ruler, Qt.MouseButton.LeftButton, pos=QPoint(12, start_y)
        )
        viewport_position = self.view.mapFromScene(QPointF(40, 35))
        global_position = self.view.viewport().mapToGlobal(viewport_position)
        ruler_position = ruler.mapFromGlobal(global_position)
        QTest.mouseMove(ruler, ruler_position, 10)
        QTest.mouseRelease(
            ruler, Qt.MouseButton.LeftButton, pos=ruler_position
        )
        self.app.processEvents()
        self.assertEqual(requested, [("y", 35)])


if __name__ == "__main__":
    unittest.main()
