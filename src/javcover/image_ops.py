from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
)

from javcover.models import MAX_CANVAS_PIXELS, DesignElement, Project


class ImageError(ValueError):
    """Raised when an image cannot be decoded or encoded."""


_BLEND_COMPOSITION_MODES = {
    "normal": QPainter.CompositionMode.CompositionMode_SourceOver,
    "multiply": QPainter.CompositionMode.CompositionMode_Multiply,
    "screen": QPainter.CompositionMode.CompositionMode_Screen,
    "overlay": QPainter.CompositionMode.CompositionMode_Overlay,
    "darken": QPainter.CompositionMode.CompositionMode_Darken,
    "lighten": QPainter.CompositionMode.CompositionMode_Lighten,
    "add": QPainter.CompositionMode.CompositionMode_Plus,
}


def composition_mode(name: str) -> QPainter.CompositionMode:
    return _BLEND_COMPOSITION_MODES.get(
        name, QPainter.CompositionMode.CompositionMode_SourceOver
    )


def load_image(path: str | Path) -> QImage:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    announced_size = reader.size()
    if (
        announced_size.width() > 0
        and announced_size.height() > 0
        and announced_size.width() * announced_size.height() > MAX_CANVAS_PIXELS
    ):
        raise ImageError("图片像素总数超过 1 亿，请先缩小图片后再导入。")
    image = reader.read()
    if image.isNull():
        raise ImageError(f"无法读取图片：{reader.errorString()}")
    if image.width() * image.height() > MAX_CANVAS_PIXELS:
        raise ImageError("图片像素总数超过 1 亿，请先缩小图片后再导入。")
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def encode_png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ImageError("无法创建图片缓存。")
    try:
        if not image.save(buffer, "PNG"):
            raise ImageError("无法将图片编码为 PNG。")
    finally:
        buffer.close()
    return bytes(data)


def decode_png(data: bytes) -> QImage:
    payload = QByteArray(data)
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
        raise ImageError("无法读取项目中的 PNG 图片数据。")
    reader = QImageReader(buffer, b"PNG")
    size = reader.size()
    if (
        size.width() <= 0
        or size.height() <= 0
        or size.width() * size.height() > MAX_CANVAS_PIXELS
    ):
        buffer.close()
        raise ImageError("项目中的 PNG 图片尺寸无效或超过 1 亿像素。")
    image = reader.read()
    buffer.close()
    if image.isNull():
        raise ImageError(f"项目中的 PNG 图片数据无效：{reader.errorString()}")
    return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def compose_project(project: Project) -> QImage:
    if project.width <= 0 or project.height <= 0:
        raise ImageError("画布尺寸无效。")
    if project.width * project.height > MAX_CANVAS_PIXELS:
        raise ImageError("画布像素总数超过 1 亿，无法导出。")
    output = QImage(
        project.width,
        project.height,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    if output.isNull():
        raise ImageError("无法分配导出画布内存。")
    output.fill(0)
    painter = QPainter(output)
    try:
        if project.base_png:
            base = decode_png(project.base_png)
            if base.width() != project.width or base.height() != project.height:
                raise ImageError("底图尺寸与画布尺寸不一致。")
            painter.drawImage(QRectF(0, 0, project.width, project.height), base)
        for region in project.regions:
            if not region.visible or not region.background_png:
                continue
            image = decode_png(region.background_png)
            target = QRectF(
                region.rect.x, region.rect.y, region.rect.width, region.rect.height
            )
            paint_region_background(
                painter, image, target, region.fit, region.opacity, region.blend_mode
            )
        for element in project.elements:
            _draw_element(painter, element)
    finally:
        painter.end()
    return output


def paint_region_background(
    painter: QPainter,
    image: QImage,
    target: QRectF,
    fit: str,
    opacity: int,
    blend_mode: str = "normal",
) -> None:
    """Draw a region's background image into ``target`` using its fit mode."""
    painter.setCompositionMode(composition_mode(blend_mode))
    if opacity < 100:
        painter.setOpacity(max(0, opacity) / 100)
    if fit == "stretch":
        painter.drawImage(target, image)
    elif fit == "contain":
        scale = min(target.width() / image.width(), target.height() / image.height())
        width = image.width() * scale
        height = image.height() * scale
        painter.drawImage(
            QRectF(
                target.x() + (target.width() - width) / 2,
                target.y() + (target.height() - height) / 2,
                width,
                height,
            ),
            image,
        )
    else:  # cover: fill and center-crop
        scale = max(target.width() / image.width(), target.height() / image.height())
        source_width = target.width() / scale
        source_height = target.height() / scale
        source = QRectF(
            (image.width() - source_width) / 2,
            (image.height() - source_height) / 2,
            source_width,
            source_height,
        )
        painter.save()
        painter.setClipRect(target)
        painter.drawImage(target, image, source)
        painter.restore()
    if opacity < 100:
        painter.setOpacity(1.0)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


def _draw_element(painter: QPainter, element: DesignElement) -> None:
    if not element.visible:
        return
    target = QRectF(element.x, element.y, element.width, element.height)
    painter.setCompositionMode(composition_mode(element.blend_mode))
    if element.opacity < 100:
        painter.setOpacity(max(0, element.opacity) / 100)
    try:
        if element.kind == "image":
            if not element.png:
                return
            painter.drawImage(target, decode_png(element.png))
            return
        paint_text_element(painter, element, target)
    finally:
        if element.opacity < 100:
            painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


def build_text_path(element: DesignElement) -> QPainterPath | None:
    """Build the glyph outline for a text element at its configured font size."""
    font = QFont(element.font_family)
    font.setPixelSize(element.font_size)
    font.setBold(element.bold)
    font.setItalic(element.italic)
    path = QPainterPath()
    metrics = QFontMetricsF(font)
    if element.vertical:
        line_height = metrics.height()
        for index, character in enumerate(element.text):
            path.addText(0, metrics.ascent() + index * line_height, font, character)
    else:
        for index, line in enumerate(element.text.splitlines() or [""]):
            path.addText(0, metrics.ascent() + index * metrics.height(), font, line)
    if path.boundingRect().isEmpty():
        return None
    return path


def paint_text_element(
    painter: QPainter, element: DesignElement, target: QRectF
) -> None:
    """Render a text element into ``target``.

    Shared by the canvas preview and the export so both show the same result:
    glyphs are drawn at the configured font size (no stretching), centered in
    the element rectangle, and clipped to it.
    """
    path = build_text_path(element)
    if path is None:
        return
    bounds = path.boundingRect()
    painter.save()
    painter.setClipRect(target)
    painter.translate(target.center() - bounds.center())
    if element.outline_width:
        outline = QPen(
            QColor(element.outline_color),
            element.outline_width * 2,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        outline.setCosmetic(True)
        painter.setPen(outline)
        painter.setBrush(QColor(element.outline_color))
        painter.drawPath(path)
    painter.setPen(QPen(Qt.PenStyle.NoPen))
    painter.setBrush(QColor(element.color))
    painter.drawPath(path)
    painter.restore()
