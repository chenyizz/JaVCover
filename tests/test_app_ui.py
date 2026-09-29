import os
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QGraphicsDropShadowEffect,
    QLabel,
    QScrollArea,
    QSplitter,
    QToolBar,
    QToolButton,
)

from javcover.app import (
    MainWindow,
    PreferencesDialog,
    _startup_path,
    format_output_name,
)
from javcover.image_ops import encode_png
from javcover.models import DesignElement, Project, Rect, Region


class MainWindowStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_compact_menu_row_and_icon_tool_rail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
            )
            window = MainWindow(settings=settings)
            window.show()
            self.app.processEvents()
            try:
                self.assertTrue(
                    window.windowFlags() & Qt.WindowType.FramelessWindowHint
                )
                self.assertFalse(window.menuBar().isHidden())
                self.assertNotIn("未命名", window.windowTitle())
                self.assertIsNotNone(
                    window.menuBar().cornerWidget(Qt.Corner.TopLeftCorner)
                )
                controls = window.menuBar().cornerWidget(Qt.Corner.TopRightCorner)
                self.assertIsNotNone(controls)
                self.assertEqual(len(controls.findChildren(type(window.minimize_button))), 4)
                window_buttons = (
                    window.minimize_button,
                    window.maximize_button,
                    window.fullscreen_button,
                    window.close_button,
                )
                self.assertEqual({button.size() for button in window_buttons}, {QSize(46, 36)})
                self.assertTrue(all(not button.text() for button in window_buttons))
                self.assertTrue(window.mask().isEmpty())
                self.assertTrue(
                    window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                )
                self.assertIn("border-bottom-left-radius: 5px;", window.styleSheet())
                self.assertIn("border-top-left-radius: 5px;", window.styleSheet())
                self.assertGreaterEqual(window.status.minimumWidth(), 320)
                self.assertEqual(window.property("windowCornerRadius"), 6)
                rounded = QPixmap(window.size())
                rounded.fill(Qt.GlobalColor.transparent)
                window.render(rounded)
                rounded_image = rounded.toImage()
                self.assertLess(rounded_image.pixelColor(0, 0).alpha(), 255)
                bottom_center = rounded_image.pixelColor(
                    rounded.width() // 2, rounded.height() - 2
                )
                self.assertGreater(bottom_center.alpha(), 0)
                self.assertGreater(bottom_center.red(), 240)
                self.assertEqual(window.windowIcon().isNull(), False)
                icon_path = Path(__file__).parents[1] / "src" / "javcover" / "icons" / "app-icon.svg"
                self.assertTrue(icon_path.is_file())
                app_icon = QIcon(str(icon_path))
                self.assertFalse(app_icon.isNull())
                icon_image = app_icon.pixmap(QSize(256, 256)).toImage()
                self.assertFalse(icon_image.isNull())
                self.assertEqual(icon_image.pixelColor(0, 0).alpha(), 0)
                self.assertFalse(window.app_mark.autoFillBackground())
                self.assertNotIn("QLabel#appMark", window.styleSheet())
                icon_directory = icon_path.parent
                control_icons = (
                    "window-minimize.svg",
                    "window-maximize.svg",
                    "window-restore.svg",
                    "window-fullscreen.svg",
                    "window-fullscreen-exit.svg",
                    "window-close.svg",
                    "window-close-hover.svg",
                )
                self.assertTrue(
                    all((icon_directory / name).is_file() for name in control_icons)
                )
                self.assertTrue(
                    all(not button.icon().isNull() for button in window_buttons)
                )
                self.assertTrue(
                    all(button.iconSize() == QSize(16, 16) for button in window_buttons)
                )
                normal_close_icon = window.close_button.icon().cacheKey()
                QApplication.sendEvent(window.close_button, QEvent(QEvent.Type.Enter))
                self.assertNotEqual(
                    window.close_button.icon().cacheKey(), normal_close_icon
                )
                QApplication.sendEvent(window.close_button, QEvent(QEvent.Type.Leave))
                normal_maximize_icon = window.maximize_button.icon().cacheKey()
                window.maximize_button.set_maximized(True)
                self.assertNotEqual(
                    window.maximize_button.icon().cacheKey(), normal_maximize_icon
                )
                normal_fullscreen_icon = window.fullscreen_button.icon().cacheKey()
                window.fullscreen_button.set_fullscreen(True)
                self.assertNotEqual(
                    window.fullscreen_button.icon().cacheKey(), normal_fullscreen_icon
                )
                self.assertFalse(
                    any(action.text() == "帮助" for action in window.menuBar().actions())
                )
                self.assertIn(
                    "设置", [action.text() for action in window.menuBar().actions()]
                )
                rail = window.findChild(QToolBar, "canvasToolRail")
                self.assertIsNotNone(rail)
                self.assertEqual(rail.orientation(), Qt.Orientation.Vertical)
                self.assertEqual(
                    rail.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly
                )
                self.assertTrue(all(not action.icon().isNull() for action in rail.actions() if not action.isSeparator()))
                options = window.findChild(QToolBar, "viewOptionsToolbar")
                self.assertIsNotNone(options)
                self.assertFalse(
                    any("新建" in action.text() or "打开" in action.text() for action in options.actions())
                )
                self.assertEqual(len(window.findChildren(QDockWidget)), 3)
                self.assertEqual(len(window.findChildren(QScrollArea)), 3)
                self.assertEqual(
                    set(window.inspector_card_scroll_areas),
                    {"区域", "参考线", "图层"},
                )
                self.assertTrue(
                    window.region_dock.features()
                    & QDockWidget.DockWidgetFeature.DockWidgetFloatable
                )
                self.assertTrue(
                    window.region_dock.features()
                    & QDockWidget.DockWidgetFeature.DockWidgetMovable
                )
                animated_buttons = [
                    button
                    for button in window.findChildren(QToolButton)
                    if button.property("javcoverAnimated")
                ]
                self.assertEqual(len(animated_buttons), 6)
                self.assertTrue(
                    all(button.iconSize().width() == 18 for button in animated_buttons)
                )
                self.assertTrue(
                    all(button.width() == 34 for button in animated_buttons)
                )
                self.assertTrue(
                    all(
                        isinstance(button.graphicsEffect(), QGraphicsDropShadowEffect)
                        for button in animated_buttons
                    )
                )
                checked_button = next(button for button in animated_buttons if button.isChecked())
                QTest.qWait(200)
                self.assertGreater(
                    checked_button.graphicsEffect().blurRadius(), 0
                )
                self.assertGreater(window.view.transform().m11(), 0)
                fitted = window.view.mapFromScene(
                    window.view.cover_scene.sceneRect()
                ).boundingRect()
                self.assertLessEqual(
                    fitted.width(), window.view.viewport().width() + 1
                )
                self.assertLessEqual(
                    fitted.height(), window.view.viewport().height() + 1
                )
                window.resize(850, 520)
                self.app.processEvents()
                region_scroll = window.inspector_card_scroll_areas["区域"]
                self.assertGreater(region_scroll.verticalScrollBar().maximum(), 0)
                window.guides_panel_action.setChecked(False)
                self.assertTrue(window.guide_dock.isHidden())
                window.guides_panel_action.setChecked(True)
                self.assertFalse(window.guide_dock.isHidden())
            finally:
                window.close()

    def test_canvas_and_inspector_preferences_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = str(Path(directory) / "ui.ini")
            first = MainWindow(
                settings=QSettings(settings_path, QSettings.Format.IniFormat)
            )
            first.grid_checkbox.setChecked(False)
            first.grid_size.setValue(72)
            first.snap_checkbox.setChecked(False)
            first._tool_actions[0].setChecked(True)
            first._apply_pasteboard_color(QColor("#dce8f0"))
            first.show()
            self.app.processEvents()
            first._save_user_interface_state()
            first.dirty = False
            first.close()

            second = MainWindow(
                settings=QSettings(settings_path, QSettings.Format.IniFormat)
            )
            second.show()
            self.app.processEvents()
            try:
                self.assertFalse(second.grid_checkbox.isChecked())
                self.assertEqual(second.grid_size.value(), 72)
                self.assertFalse(second.snap_checkbox.isChecked())
                self.assertTrue(second._tool_actions[0].isChecked())
                self.assertEqual(
                    second.view.backgroundBrush().color(), QColor("#dce8f0")
                )
                self.assertTrue(hasattr(second, "region_dock"))
                self.assertTrue(hasattr(second, "element_dock"))
                second.guides_panel_action.setChecked(False)
                second._save_user_interface_state()
                second.dirty = False
                third = MainWindow(
                    settings=QSettings(settings_path, QSettings.Format.IniFormat)
                )
                try:
                    self.assertFalse(third.guides_panel_action.isChecked())
                finally:
                    third.close()
            finally:
                second.dirty = False
                second.close()

    def test_region_lock_and_visibility_controls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            region = Region(rect=Rect(100, 100, 200, 120), name="封面")
            window.project.regions.append(region)
            window.view.refresh_overlays()
            window._refresh_region_list()
            window.show()
            self.app.processEvents()
            try:
                row_item = window.region_list.item(0)
                window.region_list.setCurrentItem(row_item)
                self.assertEqual(window.view.selected_id, region.id)
                self.assertTrue(window.region_rows[region.id].property("active"))
                QTest.mouseClick(window.region_row_controls[region.id][0], Qt.MouseButton.LeftButton)
                self.assertTrue(region.locked)
                self.assertFalse(window.region_name.isEnabled())
                self.assertFalse(window.remove_region_button.isEnabled())

                window._tool_actions[0].setChecked(True)
                self.app.processEvents()
                center = window.view.mapFromScene(QPointF(180, 150))
                original_rect = region.rect
                QTest.mousePress(window.view.viewport(), Qt.MouseButton.LeftButton, pos=center)
                QTest.mouseMove(window.view.viewport(), center + QPoint(45, 30))
                QTest.mouseRelease(
                    window.view.viewport(), Qt.MouseButton.LeftButton, pos=center + QPoint(45, 30)
                )
                QTest.keyClick(window.view, Qt.Key.Key_Delete)
                self.assertEqual(region.rect, original_rect)
                self.assertIn(region, window.project.regions)

                QTest.mouseClick(window.region_row_controls[region.id][0], Qt.MouseButton.LeftButton)
                self.assertFalse(region.locked)
                self.assertTrue(window.region_name.isEnabled())
                QTest.mouseClick(window.region_row_controls[region.id][1], Qt.MouseButton.LeftButton)
                self.assertFalse(region.visible)
                self.assertFalse(window.view.region_items[region.id].isVisible())
                self.assertIsNone(window.view._region_at(QPointF(180, 150)))
                QTest.mouseClick(window.region_row_controls[region.id][1], Qt.MouseButton.LeftButton)
                self.assertTrue(region.visible)
                self.assertTrue(window.view.region_items[region.id].isVisible())
            finally:
                window.dirty = False
                window.close()

    def test_delete_key_removes_unlocked_region(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            region = Region(rect=Rect(10, 10, 30, 30), name="封面")
            window.project.regions.append(region)
            window.view.refresh_overlays()
            window._refresh_region_list()
            window.show()
            self.app.processEvents()
            try:
                window.view.setFocus()
                window.view.select_region(region.id)
                self.app.processEvents()
                self.assertEqual(window.view.selected_id, region.id)
                QTest.keyClick(window.view, Qt.Key.Key_Delete)
                self.app.processEvents()
                self.assertNotIn(region, window.project.regions)
            finally:
                window.dirty = False
                window.close()

    def test_undo_preserves_viewport_zoom_and_scroll(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            window.show()
            self.app.processEvents()
            try:
                window.view.scale(3, 3)
                self.app.processEvents()
                region = window.project.add_region(Rect(10, 10, 20, 20))
                window.view.refresh_overlays()
                window._begin_edit()
                region.rect = Rect(30, 30, 20, 20)
                window.view.refresh_overlays()
                window._finish_edit()
                transform = window.view.transform()
                scroll = (
                    window.view.horizontalScrollBar().value(),
                    window.view.verticalScrollBar().value(),
                )
                window.undo()
                self.app.processEvents()
                self.assertEqual(window.view.transform(), transform)
                self.assertEqual(
                    (
                        window.view.horizontalScrollBar().value(),
                        window.view.verticalScrollBar().value(),
                    ),
                    scroll,
                )
            finally:
                window.dirty = False
                window.close()

    def test_fullscreen_menu_drag_is_disabled_until_fullscreen_exits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            window.show()
            self.app.processEvents()
            try:
                window._toggle_fullscreen()
                self.app.processEvents()
                self.assertTrue(window.isFullScreen())
                self.assertEqual(window.property("windowCornerRadius"), 0)
                menu_bar = window.menuBar()
                free_x = next(
                    (
                        x
                        for x in range(menu_bar.width() - 1, -1, -1)
                        if menu_bar.actionAt(QPoint(x, menu_bar.height() // 2))
                        is None
                    ),
                    None,
                )
                self.assertIsNotNone(free_x)
                window._title_drag_offset = QPoint(10, 10)
                QTest.mousePress(
                    menu_bar,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(free_x, menu_bar.height() // 2),
                )
                self.assertIsNone(window._title_drag_offset)
                QTest.mouseRelease(
                    menu_bar,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(free_x, menu_bar.height() // 2),
                )
                window.fullscreen_button.click()
                self.app.processEvents()
                self.assertFalse(window.isFullScreen())
                self.assertEqual(window.property("windowCornerRadius"), 6)
                QTest.mousePress(
                    menu_bar,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(free_x, menu_bar.height() // 2),
                )
                self.assertIsNotNone(window._title_drag_offset)
                QTest.mouseRelease(
                    menu_bar,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(free_x, menu_bar.height() // 2),
                )
            finally:
                if window.isFullScreen():
                    window._toggle_fullscreen()
                window.close()

    def test_preferences_persist_options_and_custom_shortcuts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = str(Path(directory) / "ui.ini")
            settings = QSettings(settings_path, QSettings.Format.IniFormat)
            window = MainWindow(settings=settings)
            dialog = PreferencesDialog(
                window._preference_values(), window._shortcut_bindings, window
            )
            dialog.grid_visible.setChecked(False)
            dialog.grid_size.setValue(64)
            dialog.canvas_width.setValue(1400)
            dialog.canvas_height.setValue(900)
            dialog.pasteboard_color = "#d8e5f0"
            dialog._update_color_button()
            dialog.jpeg_quality.setValue(80)
            dialog.wheel_zoom.setCurrentIndex(dialog.wheel_zoom.findData("ctrl"))
            dialog._shortcut_edits["fit-canvas"].setKeySequence(
                QKeySequence("Ctrl+Shift+F")
            )
            dialog.accept()
            self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
            window._store_preferences(dialog)
            try:
                self.assertFalse(window.grid_checkbox.isChecked())
                self.assertEqual(window.grid_size.value(), 64)
                self.assertEqual(
                    window.view.backgroundBrush().color(), QColor("#d8e5f0")
                )
                self.assertEqual(
                    window._shortcut_bindings["fit-canvas"][1].shortcut(),
                    QKeySequence("Ctrl+Shift+F"),
                )
                self.assertEqual(settings.value("canvas/defaultWidth"), 1400)
                self.assertEqual(settings.value("canvas/defaultHeight"), 900)
                self.assertEqual(settings.value("export/jpegQuality"), 80)
                self.assertEqual(settings.value("canvas/wheelZoomModifier"), "ctrl")
            finally:
                window.close()

            restored = MainWindow(
                settings=QSettings(settings_path, QSettings.Format.IniFormat)
            )
            try:
                self.assertEqual((restored.project.width, restored.project.height), (1400, 900))
                self.assertFalse(restored.grid_checkbox.isChecked())
                self.assertEqual(restored.grid_size.value(), 64)
                self.assertEqual(
                    restored._shortcut_bindings["fit-canvas"][1].shortcut(),
                    QKeySequence("Ctrl+Shift+F"),
                )
                self.assertEqual(restored._setting_int("export/jpegQuality", 95, 1, 100), 80)
            finally:
                restored.close()

    def test_unsaved_marker_tracks_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            try:
                self.assertEqual(window.windowTitle(), "JAVCover")
                window.dirty = True
                window._update_title()
                self.assertTrue(window.windowTitle().endswith("*"))
                window.dirty = False
                window._update_title()
                self.assertEqual(window.windowTitle(), "JAVCover")
            finally:
                window.dirty = False
                window.close()

    def test_background_runner_reports_success_and_clears_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            window.show()
            self.app.processEvents()
            results: list[object] = []
            try:
                window._run_background(
                    "测试任务",
                    lambda: 42,
                    results.append,
                    results.append,
                )
                for _ in range(200):
                    self.app.processEvents()
                    if results:
                        break
                    QTest.qWait(10)
                self.assertEqual(results, [42])
                self.assertIsNone(window._background_worker)
            finally:
                window.dirty = False
                window.close()

    @unittest.skipIf(
        find_spec("psd_tools") is None, "optional psd-tools dependency is not installed"
    )
    def test_places_and_refreshes_psd_title_asset(self) -> None:
        from psd_tools import PSDImage

        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            try:
                source = window.asset_directory / "title.psd"
                PSDImage.new("RGBA", (40, 20), color=(255, 0, 0, 128)).save(source)
                window._place_asset(source)
                self.assertEqual(len(window.project.elements), 1)
                element = window.project.elements[0]
                self.assertEqual(element.asset_name, "title.psd")
                self.assertEqual(element.asset_kind, "psd")
                self.assertIsNotNone(element.asset_hash)
                original_png = element.png

                PSDImage.new("RGBA", (40, 20), color=(0, 0, 255, 128)).save(source)
                window.view.select_element(element.id)
                window.refresh_selected_asset()
                self.assertNotEqual(element.png, original_png)
                self.assertEqual(element.asset_name, "title.psd")
            finally:
                window.dirty = False
                window.close()

    def test_element_lock_visibility_and_opacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            element = DesignElement(
                kind="text", x=10, y=10, width=40, height=20, name="标题", text="AB"
            )
            window.project.elements.append(element)
            window.view.refresh_overlays()
            window._refresh_element_list()
            window.view.select_element(element.id)
            self.app.processEvents()
            try:
                window._toggle_element_visible(element.id)
                self.assertFalse(element.visible)
                window._toggle_element_visible(element.id)
                self.assertTrue(element.visible)

                window._toggle_element_locked(element.id)
                self.assertTrue(element.locked)
                self.assertFalse(window.element_fields["x"].isEnabled())
                original = element.rect
                window.element_fields["x"].setValue(5)
                window._element_geometry_changed()
                self.assertEqual(element.rect, original)

                window.element_opacity.setValue(35)
                window._element_opacity_changed()
                self.assertEqual(element.opacity, 35)
            finally:
                window.dirty = False
                window.close()

    def test_layer_order_and_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            first = DesignElement(kind="text", x=0, y=0, width=20, height=20, name="a", text="A")
            second = DesignElement(kind="text", x=0, y=0, width=20, height=20, name="b", text="B")
            window.project.elements.extend([first, second])
            window.view.refresh_overlays()
            window._refresh_element_list()
            try:
                window.view.select_element(first.id)
                window.move_selected_element(1)
                self.assertIs(window.project.elements[1], first)
                window.duplicate_selected_element()
                self.assertEqual(len(window.project.elements), 3)
                clone = window.project.elements[-1]
                self.assertNotEqual(clone.id, first.id)
                self.assertTrue(clone.name.endswith("副本"))
            finally:
                window.dirty = False
                window.close()

    def test_render_batch_item_replaces_region_background(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            try:
                region = Region(rect=Rect(0, 0, 8, 8), name="封面")
                window.project.regions.append(region)
                source = Path(directory) / "art.png"
                art = QImage(4, 4, QImage.Format.Format_ARGB32)
                art.fill(QColor("#ff0000"))
                art.save(str(source), "PNG")
                destination = Path(directory) / "out.png"
                window._render_batch_item(
                    window.project, region.id, source, destination, "PNG", 95
                )
                self.assertTrue(destination.is_file())
                self.assertIsNone(region.background_png)
                result = QImage(str(destination))
                self.assertEqual(result.pixelColor(4, 4), QColor("#ff0000"))
            finally:
                window.dirty = False
                window.close()

    def test_list_rows_do_not_double_the_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            region = Region(rect=Rect(0, 0, 10, 10), name="色块候选 1")
            window.project.regions.append(region)
            element = DesignElement(
                kind="text", x=0, y=0, width=10, height=10, name="标题", text="A"
            )
            window.project.elements.append(element)
            window.view.refresh_overlays()
            window._refresh_region_list()
            window._refresh_element_list()
            try:
                region_item = window.region_list.item(0)
                self.assertEqual(region_item.text(), "")
                row = window.region_list.itemWidget(region_item)
                self.assertTrue(
                    any(
                        label.text() == region.name
                        for label in row.findChildren(QLabel)
                    )
                )
                element_item = window.element_list.item(0)
                self.assertEqual(element_item.text(), "")
                self.assertTrue(
                    window.findChild(QSplitter, "区域CardSplitter") is not None
                )
                self.assertTrue(
                    window.findChild(QSplitter, "参考线CardSplitter") is not None
                )
                self.assertTrue(
                    window.findChild(QSplitter, "图层CardSplitter") is not None
                )
            finally:
                window.dirty = False
                window.close()

    def test_delete_region_unlinks_layers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            region = Region(rect=Rect(0, 0, 20, 20), name="封面")
            element = DesignElement(
                kind="text",
                x=0,
                y=0,
                width=10,
                height=10,
                name="t",
                text="A",
                region_id=region.id,
            )
            window.project.regions.append(region)
            window.project.elements.append(element)
            window.view.refresh_overlays()
            window._refresh_region_list()
            window.view.select_region(region.id)
            try:
                window.remove_selected_region()
                self.assertEqual(len(window.project.regions), 0)
                self.assertIsNone(element.region_id)
            finally:
                window.dirty = False
                window.close()

    def test_drop_places_linked_layer_inside_region(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            region = Region(rect=Rect(0, 0, 20, 20), name="封面")
            window.project.regions.append(region)
            window.view.refresh_overlays()
            source = Path(directory) / "art.png"
            art = QImage(10, 10, QImage.Format.Format_ARGB32)
            art.fill(QColor("#00ff00"))
            art.save(str(source), "PNG")
            try:
                window._on_files_dropped([str(source)], QPointF(10, 10))
                self.assertEqual(len(window.project.elements), 1)
                element = window.project.elements[0]
                self.assertEqual(element.region_id, region.id)
                self.assertGreaterEqual(element.x, 0)
                self.assertLessEqual(element.x + element.width, region.rect.right)
                self.assertLessEqual(element.y + element.height, region.rect.bottom)
            finally:
                window.dirty = False
                window.close()

    def test_render_batch_stem_combines_multiple_regions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            try:
                red = Path(directory) / "red.png"
                blue = Path(directory) / "blue.png"
                for path, color in ((red, "#ff0000"), (blue, "#0000ff")):
                    art = QImage(4, 4, QImage.Format.Format_ARGB32)
                    art.fill(QColor(color))
                    art.save(str(path), "PNG")
                project = Project(
                    width=8,
                    height=4,
                    regions=[
                        Region(rect=Rect(0, 0, 4, 4), name="a"),
                        Region(rect=Rect(4, 0, 4, 4), name="b"),
                    ],
                )
                destination = Path(directory) / "combined.png"
                window._render_batch_stem(
                    project,
                    [(project.regions[0].id, red), (project.regions[1].id, blue)],
                    destination,
                    "PNG",
                    95,
                )
                result = QImage(str(destination))
                self.assertEqual(result.pixelColor(2, 2), QColor("#ff0000"))
                self.assertEqual(result.pixelColor(6, 2), QColor("#0000ff"))
            finally:
                window.dirty = False
                window.close()

    def test_print_guides_toggle_updates_scene(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            try:
                window.print_guides_action.setChecked(True)
                self.assertTrue(window.view.cover_scene.print_guides_visible)
                window.print_guides_action.setChecked(False)
                self.assertFalse(window.view.cover_scene.print_guides_visible)
            finally:
                window.dirty = False
                window.close()

    def test_duplicate_region_offsets_and_selects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            region = Region(rect=Rect(10, 10, 20, 20), name="封面")
            window.project.regions.append(region)
            window.view.refresh_overlays()
            window._refresh_region_list()
            window.view.select_region(region.id)
            try:
                window.duplicate_selected_region()
                self.assertEqual(len(window.project.regions), 2)
                clone = window.project.regions[1]
                self.assertNotEqual(clone.id, region.id)
                self.assertTrue(clone.name.endswith("副本"))
                self.assertEqual(window.view.selected_id, clone.id)
                self.assertGreaterEqual(clone.rect.x, 0)
                self.assertLessEqual(clone.rect.right, window.project.width)
            finally:
                window.dirty = False
                window.close()

    def test_autosave_writes_and_clears_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            recovery = Path(directory) / "recovery.javcover"
            window._recovery_enabled = True
            window._recovery_path = recovery
            try:
                window.dirty = True
                window._autosave()
                self.assertTrue(recovery.is_file())
                window._clear_recovery()
                self.assertFalse(recovery.exists())
            finally:
                window.dirty = False
                window.close()

    def test_recovery_directory_setting_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
            )
            custom = Path(directory) / "autosave"
            settings.setValue("recovery/directory", str(custom))
            window = MainWindow(settings=settings)
            try:
                window._update_recovery_path()
                self.assertEqual(
                    window._recovery_path, custom / "recovery.javcover"
                )
            finally:
                window.dirty = False
                window.close()

    def test_region_rename_from_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            region = Region(rect=Rect(0, 0, 10, 10), name="封面")
            window.project.regions.append(region)
            window.view.refresh_overlays()
            window._refresh_region_list()
            try:
                with patch(
                    "javcover.ui.main_window.QInputDialog.getText",
                    return_value=("新名称", True),
                ):
                    window._rename_region_from_list(window.region_list.item(0))
                self.assertEqual(region.name, "新名称")
            finally:
                window.dirty = False
                window.close()

    def test_batch_output_name_placeholders(self) -> None:
        self.assertEqual(
            format_output_name("{date}_{index}_{name}", "cover", 3, "20260928"),
            "20260928_003_cover",
        )
        self.assertEqual(format_output_name("", "x", 1, "d"), "")

    def test_zoom_shortcuts_and_asset_category_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            try:
                self.assertIn("zoom-in", window._shortcut_bindings)
                self.assertIn("zoom-out", window._shortcut_bindings)
                category = window.asset_directory / "logos"
                category.mkdir(parents=True, exist_ok=True)
                asset = category / "abc123_logo.png"
                art = QImage(8, 8, QImage.Format.Format_ARGB32)
                art.fill(QColor("#123456"))
                art.save(str(asset), "PNG")
                self.assertEqual(window._asset_path_for(asset.name), asset)
                element = DesignElement(
                    kind="image",
                    x=0,
                    y=0,
                    width=8,
                    height=8,
                    name="logo",
                    png=b"x",
                )
                window._link_asset(element, asset)
                self.assertEqual(element.asset_name, asset.name)
            finally:
                window.dirty = False
                window.close()

    def test_startup_path_detects_template_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "t.javcover"
            template.write_bytes(b"x")
            self.assertEqual(_startup_path(["app", str(template)]), template)
            self.assertIsNone(_startup_path(["app", "--flag"]))
            self.assertIsNone(_startup_path(["app"]))

    def test_color_assist_works_from_region_background_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            art = QImage(200, 100, QImage.Format.Format_ARGB32)
            from PySide6.QtGui import QPainter as _QPainter

            art.fill(QColor("#ff0000"))
            painter = _QPainter(art)
            painter.fillRect(100, 0, 100, 100, QColor("#0000ff"))
            painter.end()
            window.project.regions.append(
                Region(
                    rect=Rect(0, 0, 200, 100),
                    name="封面",
                    background_png=encode_png(art),
                )
            )
            window.view.refresh_overlays()
            try:
                window.run_color_block_assist()
                self.assertGreater(len(window.project.regions), 1)
            finally:
                window.dirty = False
                window.close()

    def test_grid_spin_buttons_step_and_respect_one_minimum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                settings=QSettings(
                    str(Path(directory) / "ui.ini"), QSettings.Format.IniFormat
                )
            )
            window.show()
            self.app.processEvents()
            try:
                for spin in (window.grid_size, window.grid_subdivisions):
                    self.assertEqual(spin.minimum(), 1)
                    spin.setValue(1)
                    QTest.mouseClick(
                        spin,
                        Qt.MouseButton.LeftButton,
                        pos=QPoint(spin.width() - 7, 5),
                    )
                    self.assertEqual(spin.value(), 2)
                    QTest.mouseClick(
                        spin,
                        Qt.MouseButton.LeftButton,
                        pos=QPoint(spin.width() - 7, spin.height() - 5),
                    )
                    self.assertEqual(spin.value(), 1)
                    QTest.mouseClick(
                        spin,
                        Qt.MouseButton.LeftButton,
                        pos=QPoint(spin.width() - 7, spin.height() - 5),
                    )
                    self.assertEqual(spin.value(), 1)
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
