"""Feature mixin: ExportMixin."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QColorSpace, QImage, QPainter
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget
from datetime import datetime
from importlib.util import find_spec
from javcover.core.constants import IMAGE_SUFFIXES, format_output_name
from javcover.core.errors import ImageError
from javcover.services.image_ops import compose_project, encode_png
from javcover.core.models import Project
from javcover.services.psd_import import PsdImportError
from javcover.core.tasks import TaskCancelled
from pathlib import Path
import copy


class ExportMixin:
    def _default_export_path(self) -> str:
        directory = str(self.settings.value("export/lastDir", "") or "")
        stem = self.current_path.stem if self.current_path else "cover"
        name = f"{stem}.png"
        return str(Path(directory) / name) if directory else name

    def _render_export(
        self, project: Project, destination: Path, image_format: str, quality: int
    ) -> Path:
        image = compose_project(project)
        if image_format == "JPEG":
            flattened = QImage(image.size(), QImage.Format.Format_RGB32)
            flattened.fill(QColor("#ffffff"))
            painter = QPainter(flattened)
            painter.drawImage(0, 0, image)
            painter.end()
            image = flattened
        self._apply_icc_profile(image)
        save_quality = quality if image_format == "JPEG" else -1
        if not image.save(str(destination), image_format, save_quality):
            raise ImageError("Qt 无法写入所选图片格式。")
        return destination

    def _apply_icc_profile(self, image: QImage) -> None:
        profile = str(self.settings.value("export/iccProfile", "") or "").strip()
        if not profile:
            return
        path = Path(profile)
        if not path.is_file():
            return
        try:
            space = QColorSpace.fromIccProfile(path.read_bytes())
        except OSError:
            return
        if space.isValid():
            image.setColorSpace(space)

    def _render_batch_stem(
        self,
        template_project: Project,
        region_sources: list[tuple[str, Path]],
        destination: Path,
        image_format: str,
        quality: int,
    ) -> Path:
        project = copy.deepcopy(template_project)
        filled = False
        for region_id, source in region_sources:
            region = next(
                (item for item in project.regions if item.id == region_id), None
            )
            if region is None:
                continue
            region.background_png = encode_png(self._load_asset_image(source))
            filled = True
        if not filled:
            raise ImageError("没有任何区域获得素材。")
        return self._render_export(project, destination, image_format, quality)

    def _render_batch_item(
        self,
        template_project: Project,
        region_id: str,
        source: Path,
        destination: Path,
        image_format: str,
        quality: int,
    ) -> Path:
        return self._render_batch_stem(
            template_project, [(region_id, source)], destination, image_format, quality
        )

    def _pick_directory(self, parent: QWidget, edit: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(parent, "选择文件夹", edit.text())
        if chosen:
            edit.setText(chosen)

    def export_image(self) -> None:
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出封面",
            self._default_export_path(),
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            destination = destination.with_suffix(".jpg" if "JPEG" in selected_filter else ".png")
        image_format = "JPEG" if destination.suffix.lower() in (".jpg", ".jpeg") else "PNG"
        quality = self._setting_int("export/jpegQuality", 95, 1, 100)
        project = self.project

        def work(cancel) -> Path:
            if cancel.is_set():
                raise TaskCancelled()
            return self._render_export(project, destination, image_format, quality)

        def on_success(saved: Path) -> None:
            self.settings.setValue("export/lastDir", str(saved.parent))
            self.settings.sync()
            self.status.setText(f"已导出：{saved}")

        def on_error(error: object) -> None:
            self._error("导出失败", str(error))

        self._run_background("正在导出封面…", work, on_success, on_error)

    def _render_cmyk(
        self,
        project: Project,
        destination: Path,
        profile: str,
        quality: int,
    ) -> Path:
        from io import BytesIO

        from PIL import Image, ImageCms

        image = compose_project(project)
        flattened = QImage(image.size(), QImage.Format.Format_RGB32)
        flattened.fill(QColor("#ffffff"))
        painter = QPainter(flattened)
        painter.drawImage(0, 0, image)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        flattened.save(buffer, "PNG")
        data = bytes(buffer.data())
        buffer.close()
        pil = Image.open(BytesIO(data)).convert("RGB")
        icc_bytes: bytes | None = None
        if profile:
            profile_path = Path(profile)
            if profile_path.is_file():
                icc_bytes = profile_path.read_bytes()
                try:
                    destination_profile = ImageCms.ImageCmsProfile(BytesIO(icc_bytes))
                    pil = ImageCms.profileToProfile(
                        pil,
                        ImageCms.createProfile("sRGB"),
                        destination_profile,
                        outputMode="CMYK",
                        renderingIntent=ImageCms.Intent.PERCEPTUAL,
                    )
                except Exception:  # noqa: BLE001 - fall back to a naive conversion
                    pil = pil.convert("CMYK")
            else:
                pil = pil.convert("CMYK")
        else:
            pil = pil.convert("CMYK")
        save_kwargs: dict[str, object] = {}
        if icc_bytes:
            save_kwargs["icc_profile"] = icc_bytes
        if destination.suffix.lower() in (".jpg", ".jpeg"):
            save_kwargs["quality"] = quality
        pil.save(str(destination), **save_kwargs)
        return destination

    def export_cmyk(self) -> None:
        if find_spec("PIL") is None:
            self._error(
                "需要 Pillow",
                "CMYK 导出需要 Pillow 依赖，请运行：\n"
                '.\\\\.venv\\\\Scripts\\\\python.exe -m pip install -e ".[cmyk]"',
            )
            return
        default = Path(self._default_export_path()).with_suffix(".tif")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 CMYK",
            str(default),
            "TIFF 图片 (*.tif *.tiff);;JPEG 图片 (*.jpg *.jpeg)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() not in (".tif", ".tiff", ".jpg", ".jpeg"):
            destination = destination.with_suffix(".tif")
        profile = str(self.settings.value("export/cmykProfile", "") or "")
        quality = self._setting_int("export/jpegQuality", 95, 1, 100)
        project = self.project

        def work(cancel) -> Path:
            if cancel.is_set():
                raise TaskCancelled()
            return self._render_cmyk(project, destination, profile, quality)

        def on_success(saved: Path) -> None:
            self.settings.setValue("export/lastDir", str(saved.parent))
            self.settings.sync()
            self.status.setText(f"已导出 CMYK：{saved}")

        def on_error(error: object) -> None:
            self._error("CMYK 导出失败", str(error))

        self._run_background("正在导出 CMYK…", work, on_success, on_error)

    def batch_export(self) -> None:
        if not self.project.regions:
            self._error(
                "缺少区域",
                "批量生成需要至少一个区域。请先创建区域或运行色块分析。",
            )
            return
        regions = list(self.project.regions)
        dialog = QDialog(self)
        dialog.setWindowTitle("批量生成封面（流水线）")
        dialog.resize(760, 460)
        outer = QVBoxLayout(dialog)
        hint = QLabel(
            "为每个目标区域选择一个素材文件夹；程序按文件名（不含扩展名）对应组合，"
            "例如 封面/1.jpg + 脊柱/1.jpg 一起生成 1.png。目标区域最多与模板区域数相同。"
        )
        hint.setWordWrap(True)
        outer.addWidget(hint)

        rows_container = QWidget()
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(4)
        rows_scroll = QScrollArea()
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setWidget(rows_container)
        outer.addWidget(rows_scroll, 1)
        entries: list[dict[str, object]] = []

        def remove_row(row: dict[str, object]) -> None:
            if len(entries) <= 1:
                return
            entries.remove(row)
            widget = row["widget"]
            widget.setParent(None)
            widget.deleteLater()

        def add_row(region_index: int = 0) -> None:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            combo = QComboBox()
            for region in regions:
                combo.addItem(
                    f"{region.name} ({region.rect.width}×{region.rect.height})",
                    region.id,
                )
            combo.setCurrentIndex(min(region_index, combo.count() - 1))
            folder_edit = QLineEdit()
            folder_edit.setPlaceholderText("素材文件夹…")
            browse = QPushButton("浏览…")
            remove = QPushButton("移除")
            row_layout.addWidget(QLabel("区域"))
            row_layout.addWidget(combo, 2)
            row_layout.addWidget(QLabel("素材"))
            row_layout.addWidget(folder_edit, 3)
            row_layout.addWidget(browse)
            row_layout.addWidget(remove)
            row = {"widget": row_widget, "combo": combo, "folder": folder_edit}
            entries.append(row)
            rows_layout.addWidget(row_widget)
            browse.clicked.connect(
                lambda _checked=False, edit=folder_edit: self._pick_directory(dialog, edit)
            )
            remove.clicked.connect(lambda _checked=False, r=row: remove_row(r))

        def add_target() -> None:
            if len(entries) >= len(regions):
                QMessageBox.information(
                    dialog,
                    "已达上限",
                    f"模板有 {len(regions)} 个区域，目标区域最多 {len(regions)} 个。",
                )
                return
            add_row(len(entries) % len(regions))

        add_row(0)
        add_button = QPushButton("添加目标区域")
        add_button.clicked.connect(add_target)
        outer.addWidget(add_button)

        options = QFormLayout()
        output_row = QHBoxLayout()
        output_edit = QLineEdit()
        output_browse = QPushButton("浏览…")
        output_row.addWidget(output_edit)
        output_row.addWidget(output_browse)
        options.addRow("输出文件夹", output_row)
        format_combo = QComboBox()
        format_combo.addItem("PNG", "PNG")
        format_combo.addItem("JPEG", "JPEG")
        options.addRow("输出格式", format_combo)
        pattern_edit = QLineEdit("{name}")
        pattern_edit.setToolTip("可用 {name}（素材名）、{index}（序号）、{date}（日期）")
        options.addRow("文件名模式", pattern_edit)
        outer.addLayout(options)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        outer.addWidget(buttons)
        output_browse.clicked.connect(lambda: self._pick_directory(dialog, output_edit))

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        output_dir = Path(output_edit.text().strip())
        if not output_dir.is_dir():
            self._error("文件夹无效", "请选择存在的输出文件夹。")
            return
        per_region: list[tuple[str, dict[str, Path]]] = []
        all_stems: set[str] = set()
        for row in entries:
            folder = Path(str(row["folder"].text()).strip())
            combo = row["combo"]
            if not folder.is_dir():
                self._error(
                    "文件夹无效",
                    f"请为“{combo.currentText()}”选择存在的素材文件夹。",
                )
                return
            mapping: dict[str, Path] = {}
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                    mapping.setdefault(path.stem, path)
            per_region.append((combo.currentData(), mapping))
            all_stems.update(mapping)
        if not all_stems:
            self._error("没有素材", "所选素材文件夹中没有支持的图片文件。")
            return
        image_format = format_combo.currentData()
        quality = self._setting_int("export/jpegQuality", 95, 1, 100)
        pattern = pattern_edit.text().strip() or "{name}"
        extension = ".jpg" if image_format == "JPEG" else ".png"
        template_project = copy.deepcopy(self.project)
        stems = sorted(all_stems)
        date_token = datetime.now().strftime("%Y%m%d")

        def work(cancel) -> tuple[list[Path], list[tuple[str, str]], int]:
            outputs: list[Path] = []
            failures: list[tuple[str, str]] = []
            partial = 0
            for index, stem in enumerate(stems, start=1):
                if cancel.is_set():
                    raise TaskCancelled()
                region_sources = [
                    (region_id, mapping[stem])
                    for region_id, mapping in per_region
                    if stem in mapping
                ]
                if len(region_sources) < len(per_region):
                    partial += 1
                if not region_sources:
                    continue
                name = format_output_name(pattern, stem, index, date_token)
                destination = output_dir / f"{name}{extension}"
                try:
                    self._render_batch_stem(
                        template_project,
                        region_sources,
                        destination,
                        image_format,
                        quality,
                    )
                    outputs.append(destination)
                except (ImageError, PsdImportError, OSError) as error:
                    failures.append((stem, str(error)))
            return outputs, failures, partial

        def on_success(result: tuple[list[Path], list[tuple[str, str]], int]) -> None:
            outputs, failures, partial = result
            self.settings.setValue("export/lastDir", str(output_dir))
            self.settings.sync()
            message = (
                f"批量生成完成：成功 {len(outputs)} 张，失败 {len(failures)} 张，"
                f"{partial} 张存在缺失区域素材。"
            )
            self.status.setText(message)
            if failures:
                detail = "\n".join(f"{name}：{err}" for name, err in failures[:8])
                QMessageBox.warning(self, "部分素材失败", f"{message}\n{detail}")

        def on_error(error: object) -> None:
            self._error("批量生成失败", str(error))

        self._run_background(
            f"正在批量生成 {len(stems)} 张封面…", work, on_success, on_error
        )

