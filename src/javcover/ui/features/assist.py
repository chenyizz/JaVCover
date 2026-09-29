"""Feature mixin: AssistMixin."""

from __future__ import annotations

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
from javcover.services.assist import list_tesseract_languages, recognize_japanese_text, resolve_tesseract, suggest_color_blocks
from javcover.core.errors import ImageError
from javcover.services.image_ops import compose_project
from javcover.core.models import Rect


class AssistMixin:
    def _analysis_image(self) -> QImage:
        """Image used by the color/OCR assists.

        Uses the composed cover (base + visible region backgrounds) so the tools
        also work on opened templates that carry their content as region
        backgrounds instead of a base image.
        """
        has_content = bool(self.project.base_png) or any(
            region.background_png for region in self.project.regions
        )
        if not has_content:
            raise ImageError(
                "请先导入封面图片，或为区域设置背景，再运行分析。"
            )
        return compose_project(self.project)

    def run_color_block_assist(self) -> None:
        try:
            analysis = self._analysis_image()
        except ImageError as error:
            self._error("需要底图", str(error))
            return
        try:
            candidates = suggest_color_blocks(analysis)
        except ImageError as error:
            self._error("色块分析失败", str(error))
            return
        if not candidates:
            self.status.setText("没有检测到明显的大色块边界；可以手动画框或调整参考线。")
            return
        self._begin_edit()
        for index, rect in enumerate(candidates, start=1):
            self.project.add_region(rect).name = f"色块候选 {index}"
        self.view.refresh_overlays()
        self.view.select_region(self.project.regions[-1].id)
        self._finish_edit()
        self.status.setText(f"已添加 {len(candidates)} 个色块候选，可在画布和属性栏中校正。")

    def run_ocr_assist(self) -> None:
        try:
            analysis = self._analysis_image()
        except ImageError as error:
            self._error("需要底图", str(error))
            return
        executable = str(self.settings.value("ocr/tesseractPath", "") or "") or None
        tessdata_dir = str(self.settings.value("ocr/tessdataPath", "") or "") or None

        def work(cancel) -> list[tuple[Rect, str]]:
            return recognize_japanese_text(
                analysis,
                executable=executable,
                tessdata_dir=tessdata_dir,
                cancel_event=cancel,
            )

        def on_success(candidates: list[tuple[Rect, str]]) -> None:
            self._apply_ocr_candidates(candidates)

        def on_error(error: object) -> None:
            result = QMessageBox.warning(
                self,
                "OCR 尚未配置",
                f"{error}\n\n现在打开 OCR 设置？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if result == QMessageBox.StandardButton.Yes:
                self.configure_ocr()

        self._run_background("正在本机识别日文文字…", work, on_success, on_error)

    def _apply_ocr_candidates(self, candidates: list[tuple[Rect, str]]) -> None:
        if not candidates:
            self.status.setText("OCR 未发现可用文字候选。")
            return
        clipped_candidates: list[tuple[Rect, str]] = []
        for rect, text in candidates:
            left = max(0, rect.x)
            top = max(0, rect.y)
            right = min(self.project.width, rect.right)
            bottom = min(self.project.height, rect.bottom)
            if right <= left or bottom <= top:
                continue
            clipped_candidates.append((Rect(left, top, right - left, bottom - top), text))
        if not clipped_candidates:
            self.status.setText("OCR 结果均位于画布外，没有添加区域。")
            return
        self._begin_edit()
        for clipped, text in clipped_candidates:
            region = self.project.add_region(clipped)
            region.name = f"OCR · {text[:18]}"
        self.view.refresh_overlays()
        self.view.select_region(self.project.regions[-1].id)
        self._finish_edit()
        self.status.setText(
            f"OCR 生成 {len(clipped_candidates)} 个文字区域候选；识别结果请人工校对。"
        )

    def configure_ocr(self) -> None:
        settings = self.settings
        dialog = QDialog(self)
        dialog.setWindowTitle("配置日文 OCR")
        dialog.resize(620, 260)
        layout = QVBoxLayout(dialog)
        instructions = QLabel(
            "JAVCover 使用本机 Tesseract，不会上传封面。请安装 Windows 版 "
            "Tesseract，并准备 jpn.traineddata（以及 eng.traineddata）；"
            "安装器中需勾选 Japanese language data。"
            '<br><a href="https://github.com/UB-Mannheim/tesseract/wiki">'
            "Windows 安装说明</a> · "
            '<a href="https://github.com/tesseract-ocr/tessdata_fast/blob/main/jpn.traineddata">'
            "下载官方日文语言数据</a>"
        )
        instructions.setWordWrap(True)
        instructions.setOpenExternalLinks(True)
        layout.addWidget(instructions)
        form = QFormLayout()
        executable_edit = QLineEdit(
            str(settings.value("ocr/tesseractPath", "") or "")
        )
        tessdata_edit = QLineEdit(
            str(settings.value("ocr/tessdataPath", "") or "")
        )
        executable_row = QHBoxLayout()
        executable_row.addWidget(executable_edit)
        executable_browse = QPushButton("浏览…")
        executable_row.addWidget(executable_browse)
        tessdata_row = QHBoxLayout()
        tessdata_row.addWidget(tessdata_edit)
        tessdata_browse = QPushButton("浏览…")
        tessdata_row.addWidget(tessdata_browse)
        form.addRow("tesseract.exe", executable_row)
        form.addRow("tessdata 文件夹", tessdata_row)
        layout.addLayout(form)
        check_status = QLabel("选择程序和语言目录后，点击“检查配置”。")
        check_status.setWordWrap(True)
        layout.addWidget(check_status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        check_button = buttons.addButton(
            "检查配置", QDialogButtonBox.ButtonRole.ActionRole
        )
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def browse_executable() -> None:
            path, _ = QFileDialog.getOpenFileName(
                dialog,
                "选择 Tesseract 程序",
                executable_edit.text(),
                "Tesseract (tesseract.exe);;所有文件 (*)",
            )
            if path:
                executable_edit.setText(path)

        def browse_tessdata() -> None:
            path = QFileDialog.getExistingDirectory(
                dialog, "选择包含 jpn.traineddata 的 tessdata 文件夹",
                tessdata_edit.text(),
            )
            if path:
                tessdata_edit.setText(path)

        def validate_configuration() -> bool:
            try:
                executable = resolve_tesseract(executable_edit.text().strip() or None)
                tessdata_dir = tessdata_edit.text().strip() or None
                languages = list_tesseract_languages(executable, tessdata_dir)
                missing = {"jpn", "eng"} - languages
                if missing:
                    raise RuntimeError(
                        "语言目录缺少 "
                        + ", ".join(sorted(missing))
                        + "。请安装对应的 .traineddata 文件，再重新检查。"
                    )
            except (RuntimeError, OSError) as error:
                check_status.setText(str(error))
                check_status.setStyleSheet("color: #b42318;")
                return False
            check_status.setText(
                f"配置正常：找到 jpn 和 eng。Tesseract：{executable}"
            )
            check_status.setStyleSheet("color: #137333;")
            return True

        def accept_validated() -> None:
            if not validate_configuration():
                return
            executable = resolve_tesseract(executable_edit.text().strip() or None)
            settings.setValue("ocr/tesseractPath", executable)
            settings.setValue("ocr/tessdataPath", tessdata_edit.text().strip())
            settings.sync()
            dialog.accept()

        executable_browse.clicked.connect(browse_executable)
        tessdata_browse.clicked.connect(browse_tessdata)
        check_button.clicked.connect(validate_configuration)
        buttons.accepted.connect(accept_validated)
        dialog.exec()
        dialog.deleteLater()

