"""Feature mixin: ProjectMixin."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
from javcover.core.constants import IMAGE_SUFFIXES
from javcover.core.errors import ImageError
from javcover.services.image_ops import decode_png, encode_png, load_image
from javcover.core.models import MAX_CANVAS_PIXELS, Project
from javcover.services.psd_import import import_psd
from javcover.core.tasks import TaskCancelled
from javcover.services.template_io import TemplateError, load_project, save_project
from javcover.ui.dialogs.new_canvas import NewCanvasDialog
from pathlib import Path
import copy


class ProjectMixin:
    def _begin_edit(self) -> None:
        if self._edit_before is None:
            self._edit_before = copy.deepcopy(self.project)

    def _finish_edit(self) -> None:
        if self._edit_before is not None and self._edit_before != self.project:
            self.undo_stack.append(self._edit_before)
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack.clear()
            self.dirty = True
            self._update_history_actions()
        self._edit_before = None
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_title()
        if self._recovery_enabled and self.dirty:
            self._autosave_timer.start()

    def _autosave(self) -> None:
        self._autosave_timer.stop()
        if not self.dirty:
            return
        try:
            save_project(self.project, self._recovery_path)
        except (OSError, TemplateError) as error:
            self.status.setText(f"自动保存失败：{error}")

    def _clear_recovery(self) -> None:
        try:
            self._recovery_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _offer_recovery(self) -> None:
        if not self._recovery_enabled:
            return
        path = self._recovery_path
        if not path.is_file():
            return
        if self.current_path and Path(self.current_path).is_file():
            try:
                if Path(self.current_path).stat().st_mtime >= path.stat().st_mtime:
                    self._clear_recovery()
                    return
            except OSError:
                pass
        result = QMessageBox.question(
            self,
            "恢复上次会话",
            "检测到上次未正常退出时的自动保存。是否恢复到该状态？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if result != QMessageBox.StandardButton.Yes:
            self._clear_recovery()
            return
        try:
            project = load_project(path)
            self._replace_project(project, None)
            self.dirty = True
            self._update_title()
            self.status.setText("已从自动保存恢复；请“模板另存为…”保存到正式文件。")
        except (TemplateError, ImageError, OSError) as error:
            self._error("恢复失败", str(error))
            self._clear_recovery()

    def _replace_project(self, project: Project, path: Path | None) -> None:
        self.close_all_editor_tabs()
        if project.base_png:
            base = decode_png(project.base_png)
            if base.width() != project.width or base.height() != project.height:
                raise ImageError("模板底图尺寸与画布尺寸不一致。")
        for region in project.regions:
            if region.background_png:
                decode_png(region.background_png)
        for element in project.elements:
            if element.kind == "image" and element.png:
                decode_png(element.png)
        self.view.set_project(project)
        self.project = project
        self.current_path = path
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_region_controls(None)
        self._update_history_actions()
        self._update_title()

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        dialog = NewCanvasDialog(
            self,
            self._setting_int("canvas/defaultWidth", 1200, 1, 100_000),
            self._setting_int("canvas/defaultHeight", 800, 1, 100_000),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height, shape = dialog.values()
        if width * height > MAX_CANVAS_PIXELS:
            self._error("画布尺寸过大", "画布最多支持 1 亿像素，请减小宽度或高度。")
            return
        self.settings.setValue("canvas/defaultWidth", width)
        self.settings.setValue("canvas/defaultHeight", height)
        self.settings.sync()
        self._replace_project(Project(width, height, shape=shape), None)

    def open_image(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "打开封面图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;所有文件 (*)"
        )
        if not path:
            return
        try:
            image = load_image(path)
            project = Project(image.width(), image.height(), base_png=encode_png(image))
            self._replace_project(project, None)
        except ImageError as error:
            self._error("图片读取失败", str(error))

    def open_psd(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 Photoshop 文档", "", "Photoshop 文档 (*.psd)"
        )
        if not path:
            return

        def work(cancel) -> Project:
            if cancel.is_set():
                raise TaskCancelled()
            return import_psd(path)

        def on_success(project: Project) -> None:
            self._replace_project(project, None)
            editable = sum(element.kind == "text" for element in project.elements)
            self.status.setText(
                f"已导入 PSD 并提取 {editable} 个文字图层，可直接编辑替换文字。"
                "已保留首段字体/字号/颜色等基础样式；复杂图层效果不会完整转换。"
            )

        def on_error(error: object) -> None:
            self._error("PSD 导入失败", str(error))

        self._run_background("正在导入 PSD…", work, on_success, on_error)

    def open_template(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 JAVCover 模板", "", "JAVCover 模板 (*.javcover);;所有文件 (*)"
        )
        if not path:
            return
        try:
            project = load_project(path)
            self._replace_project(project, Path(path))
        except (TemplateError, ImageError, OSError) as error:
            self._error("模板打开失败", str(error))

    def save_template(self) -> None:
        if self.current_path is None:
            self.save_template_as()
            return
        self._save_to(self.current_path)

    def save_template_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 JAVCover 模板", "", "JAVCover 模板 (*.javcover)"
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".javcover":
            destination = destination.with_suffix(".javcover")
        self._save_to(destination)

    def _save_to(self, path: Path) -> None:
        try:
            save_project(self.project, path)
        except OSError as error:
            self._error("模板保存失败", str(error))
            return
        self.current_path = path
        self.dirty = False
        self._autosave_timer.stop()
        self._clear_recovery()
        self._update_title()
        self.status.setText(f"已保存模板：{path}")

    def undo(self) -> None:
        if not self.undo_stack:
            return
        self.redo_stack.append(copy.deepcopy(self.project))
        self.project = self.undo_stack.pop()
        self.dirty = True
        self.view.set_project(self.project, preserve_view=True)
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_history_actions()
        self._update_title()

    def redo(self) -> None:
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.project))
        self.project = self.redo_stack.pop()
        self.dirty = True
        self.view.set_project(self.project, preserve_view=True)
        self._refresh_region_list()
        self._refresh_guide_list()
        self._refresh_element_list()
        self._update_history_actions()
        self._update_title()

    def _update_history_actions(self) -> None:
        if hasattr(self, "undo_action"):
            self.undo_action.setEnabled(bool(self.undo_stack))
            self.redo_action.setEnabled(bool(self.redo_stack))

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        result = QMessageBox.question(
            self,
            "未保存更改",
            "当前模板有未保存的更改。是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            self.save_template()
            return not self.dirty
        return True

    def open_path(self, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix == ".javcover":
            try:
                project = load_project(path)
                self._replace_project(project, path)
            except (TemplateError, ImageError, OSError) as error:
                self._error("模板打开失败", str(error))
        elif suffix in IMAGE_SUFFIXES:
            try:
                image = load_image(path)
                self._replace_project(
                    Project(image.width(), image.height(), base_png=encode_png(image)),
                    None,
                )
            except ImageError as error:
                self._error("图片读取失败", str(error))


