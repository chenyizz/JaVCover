"""Feature mixin: AssetMixin."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QStandardPaths, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QListView, QMessageBox, QPushButton, QVBoxLayout
from javcover.core.constants import IMAGE_SUFFIXES
from javcover.core.errors import ImageError
from javcover.services.image_ops import encode_png, load_image
from javcover.core.models import DesignElement, MAX_CANVAS_PIXELS, Rect, Region
from javcover.services.psd_import import PsdImportError, rasterize_psd
from pathlib import Path
from uuid import uuid4
import hashlib
import re
import shutil


_ASSET_PREFIX = re.compile(r"^[0-9a-f]{32}_")


def _asset_display_name(path: Path) -> str:
    """Human-facing asset name: strips the uuid uniqueness prefix."""
    stripped = _ASSET_PREFIX.sub("", path.stem)
    return stripped or path.stem




class AssetMixin:
    def _create_asset_store(self) -> None:
        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        self.asset_directory = Path(location) / "asset-library"
        self.asset_directory.mkdir(parents=True, exist_ok=True)
        self._update_recovery_path()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(4000)
        self._autosave_timer.timeout.connect(self._autosave)

    def open_asset_library(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("本机素材库")
        dialog.resize(560, 520)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "素材仅保存在本机；放入画布后会嵌入当前 .javcover 项目。"
            "PSD 标题素材会保留来源，可在 Photoshop 修改后刷新。"
            "可用分类文件夹管理素材。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        category_row = QHBoxLayout()
        category_row.addWidget(QLabel("分类"))
        category_combo = QComboBox()
        category_row.addWidget(category_combo, 1)
        new_category_button = QPushButton("新建分类…")
        category_row.addWidget(new_category_button)
        layout.addLayout(category_row)

        listing = QListWidget()
        listing.setIconSize(QSize(52, 52))
        listing.setViewMode(QListView.ViewMode.IconMode)
        listing.setResizeMode(QListView.ResizeMode.Adjust)
        listing.setGridSize(QSize(96, 96))
        listing.setMovement(QListView.Movement.Static)
        layout.addWidget(listing, 1)

        def current_category_dir() -> Path:
            data = category_combo.currentData()
            if data:
                return self.asset_directory / str(data)
            return self.asset_directory

        def relist_categories(select: str | None = None) -> None:
            category_combo.blockSignals(True)
            category_combo.clear()
            category_combo.addItem("全部", None)
            subdirs = sorted(
                (p.name for p in self.asset_directory.iterdir() if p.is_dir()),
                key=str.casefold,
            )
            for name in subdirs:
                category_combo.addItem(name, name)
            if select is not None:
                index = category_combo.findData(select)
                category_combo.setCurrentIndex(index if index >= 0 else 0)
            category_combo.blockSignals(False)

        def thumbnail(path: Path) -> QImage | None:
            if path.suffix.lower() == ".psd":
                try:
                    image = rasterize_psd(path)
                except (PsdImportError, OSError):
                    return None
                return image.scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if (
                size.width() <= 0
                or size.height() <= 0
                or size.width() * size.height() > MAX_CANVAS_PIXELS
            ):
                return None
            reader.setScaledSize(
                size.scaled(QSize(96, 96), Qt.AspectRatioMode.KeepAspectRatio)
            )
            image = reader.read()
            return None if image.isNull() else image

        def refresh() -> None:
            listing.clear()
            data = category_combo.currentData()
            if data:
                candidates = sorted((self.asset_directory / str(data)).iterdir())
            else:
                candidates = sorted(self.asset_directory.rglob("*"))
            for path in candidates:
                if not path.is_file() or path.suffix.lower() not in (
                    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".psd"
                ):
                    continue
                image = thumbnail(path)
                display = _asset_display_name(path)
                item = (
                    QListWidgetItem(QIcon(QPixmap.fromImage(image)), display)
                    if image is not None
                    else QListWidgetItem(display)
                )
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(str(path.parent))
                listing.addItem(item)

        def import_paths(paths: list[Path], target: Path) -> None:
            target.mkdir(parents=True, exist_ok=True)
            for src in paths:
                if not src.is_file() or src.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                destination = target / f"{uuid4().hex}_{src.name}"
                try:
                    self._load_asset_image(src)
                    shutil.copy2(src, destination)
                except (ImageError, PsdImportError, OSError) as error:
                    self._error("素材导入失败", f"{src.name}：{error}")
            refresh()

        def import_assets() -> None:
            paths, _ = QFileDialog.getOpenFileNames(
                dialog,
                "导入素材",
                "",
                "图片与 PSD (*.png *.jpg *.jpeg *.webp *.bmp *.psd);;所有文件 (*)",
            )
            if paths:
                import_paths([Path(p) for p in paths], current_category_dir())

        def import_folder() -> None:
            chosen = QFileDialog.getExistingDirectory(
                dialog, "导入素材文件夹（含子文件夹）", ""
            )
            if not chosen:
                return
            folder = Path(chosen)
            files = [p for p in folder.rglob("*") if p.is_file()]
            if not files:
                self._error("没有素材", "所选文件夹中没有文件。")
                return
            import_paths(files, current_category_dir())

        def create_category() -> None:
            name, accepted = QInputDialog.getText(dialog, "新建分类", "分类名称")
            if not accepted:
                return
            name = name.strip()
            if not name:
                return
            target = self.asset_directory / name
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self._error("创建分类失败", str(error))
                return
            relist_categories(name)
            refresh()

        def place_selected() -> None:
            item = listing.currentItem()
            if item is None:
                return
            dialog.accept()
            self._place_asset(Path(item.data(Qt.ItemDataRole.UserRole)))

        def delete_selected() -> None:
            items = listing.selectedItems()
            if not items:
                return
            if len(items) == 1:
                label = _asset_display_name(Path(items[0].data(Qt.ItemDataRole.UserRole)))
                message = f"从本机素材库删除“{label}”？\n已放入画布的图层不受影响。"
            else:
                message = (
                    f"从本机素材库删除选中的 {len(items)} 个素材？\n"
                    "已放入画布的图层不受影响。"
                )
            confirmed = QMessageBox.question(
                dialog,
                "删除素材",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmed != QMessageBox.StandardButton.Yes:
                return
            for item in items:
                path = Path(item.data(Qt.ItemDataRole.UserRole))
                try:
                    path.unlink()
                except OSError as error:
                    self._error("删除素材失败", str(error))
            refresh()

        def rename_selected() -> None:
            item = listing.currentItem()
            if item is None:
                return
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            current = _asset_display_name(path)
            name, accepted = QInputDialog.getText(
                dialog, "重命名素材", "名称", text=current
            )
            name = name.strip()
            if not accepted or not name or name == current:
                return
            match = _ASSET_PREFIX.match(path.stem)
            prefix = match.group(0) if match else ""
            destination = path.with_name(f"{prefix}{name}{path.suffix}")
            if destination.exists():
                self._error("重命名失败", "同名素材已存在。")
                return
            old_name = path.name
            try:
                path.rename(destination)
            except OSError as error:
                self._error("重命名失败", str(error))
                return
            for element in self.project.elements:
                if element.asset_name == old_name:
                    element.asset_name = destination.name
            refresh()

        category_combo.currentIndexChanged.connect(lambda _index: refresh())
        new_category_button.clicked.connect(create_category)
        listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        select_all = QShortcut(
            QKeySequence(QKeySequence.StandardKey.SelectAll), listing
        )
        select_all.activated.connect(listing.selectAll)
        rename_shortcut = QShortcut(QKeySequence("F2"), listing)
        rename_shortcut.activated.connect(rename_selected)
        delete_shortcut = QShortcut(
            QKeySequence(QKeySequence.StandardKey.Delete), listing
        )
        delete_shortcut.activated.connect(delete_selected)
        buttons = QHBoxLayout()
        add_button = QPushButton("导入文件…")
        add_button.clicked.connect(import_assets)
        folder_button = QPushButton("导入文件夹…")
        folder_button.clicked.connect(import_folder)
        rename_button = QPushButton("重命名")
        rename_button.clicked.connect(rename_selected)
        delete_button = QPushButton("删除素材")
        delete_button.clicked.connect(delete_selected)
        place_button = QPushButton("放入画布")
        place_button.clicked.connect(place_selected)
        buttons.addWidget(add_button)
        buttons.addWidget(folder_button)
        buttons.addWidget(rename_button)
        buttons.addWidget(delete_button)
        buttons.addStretch(1)
        buttons.addWidget(place_button)
        layout.addLayout(buttons)
        listing.itemDoubleClicked.connect(lambda _item: place_selected())
        relist_categories()
        refresh()
        dialog.exec()
        dialog.deleteLater()

    def _link_asset(self, element: DesignElement, path: Path) -> None:
        try:
            path.relative_to(self.asset_directory)
        except ValueError:
            return
        element.asset_name = path.name
        element.asset_kind = "psd" if path.suffix.lower() == ".psd" else "image"
        try:
            element.asset_hash = self._hash_file(path)
        except OSError:
            element.asset_hash = None

    def _build_image_element(
        self, image: QImage, path: Path, scene_pos: QPointF, region: Region | None
    ) -> DesignElement:
        if region is not None:
            fitted = image.scaled(
                min(image.width(), region.rect.width),
                min(image.height(), region.rect.height),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            rect = Rect(
                int(scene_pos.x() - fitted.width() / 2),
                int(scene_pos.y() - fitted.height() / 2),
                fitted.width(),
                fitted.height(),
            ).bounded_within(region.rect)
            element = DesignElement(
                kind="image",
                x=rect.x,
                y=rect.y,
                width=rect.width,
                height=rect.height,
                name=_asset_display_name(path),
                png=encode_png(fitted),
                region_id=region.id,
            )
        else:
            if image.width() > self.project.width or image.height() > self.project.height:
                image = image.scaled(
                    min(image.width(), self.project.width),
                    min(image.height(), self.project.height),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            rect = Rect(
                int(scene_pos.x() - image.width() / 2),
                int(scene_pos.y() - image.height() / 2),
                image.width(),
                image.height(),
            ).bounded(self.project.width, self.project.height)
            element = DesignElement(
                kind="image",
                x=rect.x,
                y=rect.y,
                width=rect.width,
                height=rect.height,
                name=_asset_display_name(path),
                png=encode_png(image),
            )
        self._link_asset(element, path)
        return element

    def _on_files_dropped(self, paths: list[str], scene_pos: QPointF) -> None:
        if self.project is None or not paths:
            return
        region = self.view._region_at(scene_pos)
        self._begin_edit()
        placed: list[DesignElement] = []
        for raw in paths:
            path = Path(raw)
            try:
                image = self._load_asset_image(path)
            except (ImageError, PsdImportError, OSError) as error:
                self._error("素材读取失败", f"{path.name}：{error}")
                continue
            placed.append(self._build_image_element(image, path, scene_pos, region))
        if not placed:
            self._edit_before = None
            return
        self.project.elements.extend(placed)
        self.view.refresh_overlays()
        self.view.select_element(placed[-1].id)
        self._finish_edit()
        if region is not None:
            self.status.setText(f"已将 {len(placed)} 个图层放入区域“{region.name}”。")
        else:
            self.status.setText(f"已放置 {len(placed)} 个图层。")

    def _place_asset(self, path: Path) -> None:
        try:
            image = self._load_asset_image(path)
        except (ImageError, PsdImportError, OSError) as error:
            self._error("素材读取失败", str(error))
            return
        element = self._build_image_element(
            image, path, QPointF(self.project.width / 2, self.project.height / 2), None
        )
        self._begin_edit()
        self.project.elements.append(element)
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()

    def place_psd_title_asset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "放置 PSD 标题素材", "", "Photoshop 文档 (*.psd)"
        )
        if not path:
            return
        try:
            destination = self._import_into_assets(Path(path))
        except OSError as error:
            self._error("素材导入失败", str(error))
            return
        self._place_asset(destination)

    def refresh_selected_asset(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.kind != "image" or not element.asset_name:
            self._error("无法刷新", "请先选择一个从素材库放置的图片图层。")
            return
        path = self._asset_path_for(element.asset_name)
        if path is None:
            self._error(
                "素材缺失",
                f"素材库中找不到“{element.asset_name}”。可使用“重新链接素材”指向新文件。",
            )
            return
        self._replace_element_asset(element, path)

    def relink_selected_asset(self) -> None:
        element = self.view._element(self.view.selected_element_id)
        if element is None or element.kind != "image":
            self._error("无法重新链接", "请先选择一个图片图层。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "重新链接素材",
            "",
            "图片与 PSD (*.psd *.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)",
        )
        if not path:
            return
        source = Path(path)
        try:
            destination = (
                source
                if source.parent == self.asset_directory
                else self._import_into_assets(source)
            )
        except OSError as error:
            self._error("素材导入失败", str(error))
            return
        self._replace_element_asset(element, destination)

    def _replace_element_asset(self, element: DesignElement, path: Path) -> None:
        try:
            encoded = encode_png(self._load_asset_image(path))
            digest = self._hash_file(path)
        except (ImageError, PsdImportError, OSError) as error:
            self._error("素材刷新失败", str(error))
            return
        self._begin_edit()
        element.png = encoded
        element.asset_name = path.name
        element.asset_kind = "psd" if path.suffix.lower() == ".psd" else "image"
        element.asset_hash = digest
        self.view.refresh_overlays()
        self.view.select_element(element.id)
        self._finish_edit()
        self.status.setText(f"已从素材刷新：{element.name}")

    def _load_asset_image(self, path: Path) -> QImage:
        if path.suffix.lower() == ".psd":
            return rasterize_psd(path)
        return load_image(path)

    def _import_into_assets(self, source: Path) -> Path:
        destination = self.asset_directory / f"{uuid4().hex}_{source.name}"
        shutil.copy2(source, destination)
        return destination

    def _asset_path_for(self, asset_name: str) -> Path | None:
        if not asset_name or "/" in asset_name or "\\" in asset_name:
            return None
        direct = self.asset_directory / asset_name
        if direct.is_file():
            return direct
        for candidate in self.asset_directory.rglob(asset_name):
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

