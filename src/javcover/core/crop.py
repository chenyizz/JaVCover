"""Crop/compose geometry for images placed in a target rectangle.

Kept free of ``image_ops`` imports (no encoding here) so the canvas crop tool,
the dedicated editor dialog and the export path can share one implementation.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage

from javcover.core.errors import ImageError


def image_rect_mapping(
    image: QImage, target: QRectF, fit: str, offset: tuple[int, int] = (0, 0)
) -> tuple[QRectF, QRectF]:
    """Return ``(drawn_rect, source_rect)`` mapping an image into ``target``."""
    width, height = image.width(), image.height()
    offset_x, offset_y = offset
    if fit == "stretch":
        return target, QRectF(0, 0, width, height)
    if fit == "contain":
        scale = min(target.width() / width, target.height() / height)
        drawn_width, drawn_height = width * scale, height * scale
        x = target.x() + (target.width() - drawn_width) / 2 + offset_x
        y = target.y() + (target.height() - drawn_height) / 2 + offset_y
        x = min(max(target.x(), x), target.x() + target.width() - drawn_width)
        y = min(max(target.y(), y), target.y() + target.height() - drawn_height)
        return QRectF(x, y, drawn_width, drawn_height), QRectF(0, 0, width, height)
    scale = max(target.width() / width, target.height() / height)
    source_width = target.width() / scale
    source_height = target.height() / scale
    source_x = (width - source_width) / 2 + offset_x * source_width / target.width()
    source_y = (height - source_height) / 2 + offset_y * source_height / target.height()
    source_x = min(max(0.0, source_x), width - source_width)
    source_y = min(max(0.0, source_y), height - source_height)
    return target, QRectF(source_x, source_y, source_width, source_height)


def crop_image_to_rect(
    image: QImage,
    target: QRectF,
    fit: str,
    crop: QRectF,
    offset: tuple[int, int] = (0, 0),
) -> tuple[QImage, QRectF]:
    """Crop ``image`` to ``crop`` (in target/scene coords).

    Returns the cropped image and the scene rect it occupies afterwards.
    """
    drawn, source = image_rect_mapping(image, target, fit, offset)
    clipped = crop.normalized().intersected(drawn)
    if clipped.width() < 1 or clipped.height() < 1:
        raise ImageError("裁剪区域无效。")
    factor_x = source.width() / drawn.width()
    factor_y = source.height() / drawn.height()
    source_x = source.x() + (clipped.x() - drawn.x()) * factor_x
    source_y = source.y() + (clipped.y() - drawn.y()) * factor_y
    source_w = max(1, round(clipped.width() * factor_x))
    source_h = max(1, round(clipped.height() * factor_y))
    sub = image.copy(
        int(round(source_x)), int(round(source_y)), int(source_w), int(source_h)
    )
    return sub, clipped
