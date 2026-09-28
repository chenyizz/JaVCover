from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PySide6.QtGui import QImage

from javcover.image_ops import encode_png
from javcover.models import MAX_CANVAS_PIXELS, DesignElement, Project


class PsdImportError(ValueError):
    """Raised when a PSD cannot be converted into an editable project."""


def _style_color(values: tuple[float, ...] | None, fallback: str) -> str:
    if values is None:
        return fallback
    components = values[1:4] if len(values) >= 4 else values[:3]
    if len(components) != 3:
        return fallback
    red, green, blue = (
        max(0, min(255, round(component * 255))) for component in components
    )
    return f"#{red:02x}{green:02x}{blue:02x}"


def _text_style(layer: Any) -> dict[str, Any]:
    from psd_tools.api.typesetting import WritingDirection

    typesetting = layer.typesetting
    if not typesetting.runs:
        return {}
    style = typesetting.runs[0].style
    font = style.font
    family = (font.family or font.postscript_name) if font else style.font_name
    return {
        "font_family": family or "Yu Gothic UI",
        "font_size": max(1, min(512, round(style.font_size * 96 / 72))),
        "color": _style_color(style.fill_color, "#ffffff"),
        "outline_color": _style_color(style.stroke_color, "#10131b"),
        "outline_width": 2 if style.stroke_flag else 0,
        "bold": style.faux_bold or bool(font and "bold" in font.style.lower()),
        "italic": style.faux_italic or bool(font and "italic" in font.style.lower()),
        "vertical": typesetting.writing_direction == WritingDirection.VERTICAL_RL,
    }


def import_psd(path: str | Path) -> Project:
    try:
        from psd_tools import PSDImage
    except ImportError as error:
        raise PsdImportError(
            "PSD 导入需要可选依赖 psd-tools。请运行 "
            "python -m pip install -e \".[psd]\" 后重试。"
        ) from error

    try:
        document = PSDImage.open(path)
        if document.width <= 0 or document.height <= 0:
            raise PsdImportError("PSD 画布尺寸无效。")
        if document.width * document.height > MAX_CANVAS_PIXELS:
            raise PsdImportError("PSD 画布超过 1 亿像素，请先缩小后导入。")
        text_layers = [
            layer
            for layer in document.descendants()
            if layer.kind == "type" and layer.visible and layer.text.strip()
        ]
        visibility = [(layer, layer.visible) for layer in text_layers]
        try:
            for layer, _ in visibility:
                layer.visible = False
            composite = document.composite()
        finally:
            for layer, was_visible in visibility:
                layer.visible = was_visible
        if composite is None:
            raise PsdImportError("PSD 没有可合成的图像内容。")
        image_bytes = BytesIO()
        composite.save(image_bytes, format="PNG")
        base = QImage.fromData(image_bytes.getvalue(), "PNG")
        if base.isNull():
            raise PsdImportError("无法解码 PSD 的合成图像。")
        project = Project(base.width(), base.height(), base_png=encode_png(base))
        for layer in text_layers:
            text = layer.text.strip()
            if len(text) > 100_000:
                raise PsdImportError(f"文字图层“{layer.name}”内容过长，无法作为可编辑图层导入。")
            x = max(0, int(layer.left))
            y = max(0, int(layer.top))
            right = min(project.width, int(layer.right))
            bottom = min(project.height, int(layer.bottom))
            if not text or right <= x or bottom <= y:
                continue
            project.elements.append(
                DesignElement(
                    kind="text",
                    x=x,
                    y=y,
                    width=right - x,
                    height=bottom - y,
                    name=(layer.name or "PSD 文字")[:256],
                    text=text,
                    **_text_style(layer),
                )
            )
        return project
    except PsdImportError:
        raise
    except Exception as error:
        raise PsdImportError(f"PSD 导入失败：{error}") from error


def rasterize_psd(path: str | Path) -> QImage:
    """Rasterize any PSD composite into a QImage.

    Unlike :func:`import_psd_overlay`, this places no same-size or
    transparency requirement, so a standalone title/word-art PSD can be
    reused as a placement asset.
    """
    try:
        from psd_tools import PSDImage
    except ImportError as error:
        raise PsdImportError(
            "PSD 导入需要可选依赖 psd-tools。请运行 "
            'python -m pip install -e ".[psd]" 后重试。'
        ) from error

    try:
        document = PSDImage.open(path)
        if document.width <= 0 or document.height <= 0:
            raise PsdImportError("PSD 画布尺寸无效。")
        if document.width * document.height > MAX_CANVAS_PIXELS:
            raise PsdImportError("PSD 画布超过 1 亿像素，请先缩小后导入。")
        composite = document.composite()
        if composite is None:
            raise PsdImportError("PSD 没有可合成的图像内容。")
        image_bytes = BytesIO()
        composite.save(image_bytes, format="PNG")
        image = QImage.fromData(image_bytes.getvalue(), "PNG")
        if image.isNull():
            raise PsdImportError("无法解码 PSD 的合成图像。")
        return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    except PsdImportError:
        raise
    except Exception as error:
        raise PsdImportError(f"PSD 读取失败：{error}") from error


def import_psd_overlay(path: str | Path) -> DesignElement:
    """Rasterize a PSD document into a transparent, canvas-sized image layer."""
    try:
        from psd_tools import PSDImage
    except ImportError as error:
        raise PsdImportError(
            "PSD 导入需要可选依赖 psd-tools。请运行 "
            'python -m pip install -e ".[psd]" 后重试。'
        ) from error

    try:
        document = PSDImage.open(path)
        if document.width <= 0 or document.height <= 0:
            raise PsdImportError("PSD 画布尺寸无效。")
        if document.width * document.height > MAX_CANVAS_PIXELS:
            raise PsdImportError("PSD 画布超过 1 亿像素，请先缩小后导入。")
        composite = document.composite()
        if composite is None:
            raise PsdImportError("PSD 没有可合成的图像内容。")
        alpha_min, alpha_max = (
            composite.getchannel("A").getextrema()
            if "A" in composite.getbands()
            else (255, 255)
        )
        if alpha_min == 255:
            raise PsdImportError(
                "PSD 合成结果没有透明区域。请隐藏或删除铺满画布的背景层后再作为图层导入。"
            )
        if alpha_max == 0:
            raise PsdImportError("PSD 没有可见图层内容，无法作为图层导入。")
        image_bytes = BytesIO()
        composite.save(image_bytes, format="PNG")
        image = QImage.fromData(image_bytes.getvalue(), "PNG")
        if image.isNull():
            raise PsdImportError("无法解码 PSD 的合成图像。")
        return DesignElement(
            kind="image",
            x=0,
            y=0,
            width=image.width(),
            height=image.height(),
            name=f"{Path(path).stem} · PSD",
            png=encode_png(image),
        )
    except PsdImportError:
        raise
    except Exception as error:
        raise PsdImportError(f"PSD 图层导入失败：{error}") from error
