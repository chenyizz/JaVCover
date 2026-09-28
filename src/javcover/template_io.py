from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from PySide6.QtGui import QColor

from javcover.models import (
    DesignElement,
    Guide,
    MAX_CANVAS_PIXELS,
    Project,
    Rect,
    Region,
    REGION_FIT_MODES,
    BLEND_MODES,
)

FORMAT_VERSION = 6
SUPPORTED_VERSIONS = (1, 2, 3, 4, 5, FORMAT_VERSION)
MAX_MANIFEST_BYTES = 5 * 1024 * 1024
MAX_ASSET_BYTES = 64 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 256 * 1024 * 1024
MAX_REGIONS = 10_000
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_REGION_ID = re.compile(r"^[a-f0-9]{32}$")


class TemplateError(ValueError):
    """Raised when a project file is invalid or cannot be read."""


def save_project(project: Project, path: str | Path) -> None:
    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "canvas": {"width": project.width, "height": project.height},
        "base_image": "assets/base.png" if project.base_png else None,
        "regions": [],
        "guides": [{"axis": guide.axis, "position": guide.position} for guide in project.guides],
        "elements": [],
    }
    assets: dict[str, bytes] = {}
    if project.base_png:
        assets["assets/base.png"] = project.base_png
    for region in project.regions:
        background_path = f"assets/regions/{region.id}.png" if region.background_png else None
        if background_path:
            assets[background_path] = region.background_png or b""
        manifest["regions"].append(
            {
                "id": region.id,
                "name": region.name,
                "rect": {
                    "x": region.rect.x,
                    "y": region.rect.y,
                    "width": region.rect.width,
                    "height": region.rect.height,
                },
                "background_image": background_path,
                "locked": region.locked,
                "visible": region.visible,
                "opacity": region.opacity,
                "fit": region.fit,
                "blend_mode": region.blend_mode,
            }
        )
    for element in project.elements:
        image_path = f"assets/elements/{element.id}.png" if element.png else None
        if image_path:
            assets[image_path] = element.png or b""
        manifest["elements"].append(
            {
                "id": element.id,
                "kind": element.kind,
                "name": element.name,
                "rect": {
                    "x": element.x,
                    "y": element.y,
                    "width": element.width,
                    "height": element.height,
                },
                "image": image_path,
                "text": element.text,
                "font_family": element.font_family,
                "font_size": element.font_size,
                "color": element.color,
                "outline_color": element.outline_color,
                "outline_width": element.outline_width,
                "bold": element.bold,
                "italic": element.italic,
                "vertical": element.vertical,
                "locked": element.locked,
                "visible": element.visible,
                "opacity": element.opacity,
                "blend_mode": element.blend_mode,
                "region_id": element.region_id,
                "asset_name": element.asset_name,
                "asset_kind": element.asset_kind,
                "asset_hash": element.asset_hash,
            }
        )

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".tmp",
            prefix=f".{destination.name}.",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for asset_path, contents in assets.items():
                archive.writestr(asset_path, contents)
        os.replace(temporary_path, destination)
    except BaseException:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise


def load_project(path: str | Path) -> Project:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            manifest_info = archive.getinfo("project.json")
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise TemplateError("模板清单过大。")
            manifest = json.loads(archive.read("project.json"))
            if (
                not isinstance(manifest, dict)
                or isinstance(manifest.get("format_version"), bool)
                or manifest.get("format_version") not in SUPPORTED_VERSIONS
            ):
                raise TemplateError("模板格式版本不受支持。")
            format_version = manifest["format_version"]
            canvas = manifest.get("canvas")
            width = _positive_int(canvas, "width")
            height = _positive_int(canvas, "height")
            if width * height > MAX_CANVAS_PIXELS:
                raise TemplateError("模板画布尺寸超过安全上限。")
            if not isinstance(manifest.get("regions"), list) or not isinstance(
                manifest.get("guides"), list
            ):
                raise TemplateError("模板缺少区域或参考线列表。")
            if format_version >= 2 and not isinstance(manifest.get("elements"), list):
                raise TemplateError("模板缺少设计元素列表。")
            if len(manifest["regions"]) > MAX_REGIONS:
                raise TemplateError("模板区域数量超过安全上限。")
            if len(manifest.get("elements", [])) > MAX_REGIONS:
                raise TemplateError("模板设计元素数量超过安全上限。")
            if sum(info.file_size for info in archive.infolist()) > MAX_TOTAL_ASSET_BYTES:
                raise TemplateError("模板文件展开后超过安全上限。")

            project = Project(width=width, height=height)
            base_path = manifest.get("base_image")
            if base_path is not None:
                project.base_png = _read_asset(archive, _asset_path(base_path))

            seen_ids: set[str] = set()
            for entry in manifest["regions"]:
                if not isinstance(entry, dict):
                    raise TemplateError("区域数据格式无效。")
                region_id = entry.get("id")
                if not isinstance(region_id, str) or not _REGION_ID.fullmatch(region_id):
                    raise TemplateError("区域 ID 格式无效。")
                if region_id in seen_ids:
                    raise TemplateError("模板中存在重复区域。")
                seen_ids.add(region_id)
                rect_data = entry.get("rect")
                rect = Rect(
                    _integer(rect_data, "x"),
                    _integer(rect_data, "y"),
                    _positive_int(rect_data, "width"),
                    _positive_int(rect_data, "height"),
                )
                if rect.x < 0 or rect.y < 0 or rect.right > width or rect.bottom > height:
                    raise TemplateError("区域超出画布范围。")
                name = entry.get("name")
                if not isinstance(name, str):
                    raise TemplateError("区域名称格式无效。")
                background_path = entry.get("background_image")
                background = (
                    _read_asset(archive, _asset_path(background_path))
                    if background_path is not None
                    else None
                )
                project.regions.append(
                    Region(
                        rect=rect,
                        name=name,
                        id=region_id,
                        background_png=background,
                        locked=_bool(entry, "locked", False),
                        visible=_bool(entry, "visible", True),
                        opacity=_opacity(entry),
                        fit=_fit_mode(entry),
                        blend_mode=_blend_mode(entry),
                    )
                )

            for entry in manifest["guides"]:
                if not isinstance(entry, dict) or entry.get("axis") not in ("x", "y"):
                    raise TemplateError("参考线数据格式无效。")
                position = _integer(entry, "position")
                limit = width if entry["axis"] == "x" else height
                if not 0 <= position <= limit:
                    raise TemplateError("参考线超出画布范围。")
                project.guides.append(Guide(entry["axis"], position))

            seen_elements: set[str] = set()
            for entry in manifest.get("elements", []):
                if not isinstance(entry, dict):
                    raise TemplateError("设计元素数据格式无效。")
                element_id = entry.get("id")
                if not isinstance(element_id, str) or not _REGION_ID.fullmatch(element_id):
                    raise TemplateError("设计元素 ID 格式无效。")
                if element_id in seen_elements:
                    raise TemplateError("模板中存在重复设计元素。")
                seen_elements.add(element_id)
                kind = entry.get("kind")
                if kind not in ("image", "text"):
                    raise TemplateError("设计元素类型不受支持。")
                rect_data = entry.get("rect")
                rect = Rect(
                    _integer(rect_data, "x"),
                    _integer(rect_data, "y"),
                    _positive_int(rect_data, "width"),
                    _positive_int(rect_data, "height"),
                )
                if rect.x < 0 or rect.y < 0 or rect.right > width or rect.bottom > height:
                    raise TemplateError("设计元素超出画布范围。")
                name = entry.get("name")
                if not isinstance(name, str):
                    raise TemplateError("设计元素名称格式无效。")
                image_path = entry.get("image")
                image_data = (
                    _read_asset(archive, _asset_path(image_path))
                    if image_path is not None
                    else None
                )
                text = entry.get("text", "")
                font_family = entry.get("font_family", "Yu Gothic UI")
                font_size = entry.get("font_size", 48)
                color = entry.get("color", "#ffffff")
                outline_color = entry.get("outline_color", "#10131b")
                outline_width = entry.get("outline_width", 0)
                if not isinstance(text, str) or not isinstance(font_family, str):
                    raise TemplateError("文字内容或字体格式无效。")
                if len(name) > 256 or len(text) > 100_000 or len(font_family) > 256:
                    raise TemplateError("设计元素的名称、文字或字体信息过长。")
                if (
                    isinstance(font_size, bool)
                    or not isinstance(font_size, int)
                    or not 1 <= font_size <= 4096
                ):
                    raise TemplateError("文字字号超出有效范围。")
                if (
                    isinstance(outline_width, bool)
                    or not isinstance(outline_width, int)
                    or not 0 <= outline_width <= 256
                ):
                    raise TemplateError("文字描边超出有效范围。")
                if not isinstance(color, str) or not isinstance(outline_color, str):
                    raise TemplateError("文字颜色格式无效。")
                if not QColor(color).isValid() or not QColor(outline_color).isValid():
                    raise TemplateError("文字颜色值无效。")
                if kind == "image" and image_data is None:
                    raise TemplateError("图片元素缺少图片资源。")
                asset_name = entry.get("asset_name")
                if asset_name is not None and (
                    not isinstance(asset_name, str)
                    or not asset_name
                    or len(asset_name) > 256
                    or "/" in asset_name
                    or "\\" in asset_name
                    or ".." in Path(asset_name).parts
                ):
                    raise TemplateError("设计元素素材名称无效。")
                asset_kind = entry.get("asset_kind")
                if asset_kind not in (None, "psd", "image"):
                    raise TemplateError("设计元素素材类型无效。")
                asset_hash = entry.get("asset_hash")
                if asset_hash is not None and (
                    not isinstance(asset_hash, str) or len(asset_hash) > 128
                ):
                    raise TemplateError("设计元素素材校验值无效。")
                region_id = entry.get("region_id")
                if region_id is not None:
                    if not isinstance(region_id, str) or not _REGION_ID.fullmatch(region_id):
                        raise TemplateError("设计元素关联区域无效。")
                    if not any(region.id == region_id for region in project.regions):
                        region_id = None
                project.elements.append(
                    DesignElement(
                        kind=kind,
                        x=rect.x,
                        y=rect.y,
                        width=rect.width,
                        height=rect.height,
                        name=name,
                        id=element_id,
                        png=image_data,
                        text=text,
                        font_family=font_family,
                        font_size=font_size,
                        color=color,
                        outline_color=outline_color,
                        outline_width=outline_width,
                        bold=_bool(entry, "bold", False),
                        italic=_bool(entry, "italic", False),
                        vertical=_bool(entry, "vertical", False),
                        locked=_bool(entry, "locked", False),
                        visible=_bool(entry, "visible", True),
                        opacity=_opacity(entry),
                        blend_mode=_blend_mode(entry),
                        region_id=region_id,
                        asset_name=asset_name,
                        asset_kind=asset_kind,
                        asset_hash=asset_hash,
                    )
                )
            return project
    except TemplateError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, TypeError) as error:
        raise TemplateError(f"无法读取模板：{error}") from error


def _integer(value: Any, key: str) -> int:
    if not isinstance(value, dict):
        raise TemplateError("模板数值字段格式无效。")
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise TemplateError(f"模板字段 {key} 必须是整数。")
    return result


def _positive_int(value: Any, key: str) -> int:
    result = _integer(value, key)
    if result <= 0:
        raise TemplateError(f"模板字段 {key} 必须大于零。")
    return result


def _bool(value: Any, key: str, default: bool) -> bool:
    if not isinstance(value, dict):
        raise TemplateError("模板布尔字段格式无效。")
    result = value.get(key, default)
    if not isinstance(result, bool):
        raise TemplateError(f"模板字段 {key} 必须是布尔值。")
    return result


def _opacity(value: Any) -> int:
    if not isinstance(value, dict):
        raise TemplateError("模板不透明度字段格式无效。")
    result = value.get("opacity", 100)
    if isinstance(result, bool) or not isinstance(result, int) or not 0 <= result <= 100:
        raise TemplateError("模板不透明度必须是 0–100 的整数。")
    return result


def _fit_mode(value: Any) -> str:
    if not isinstance(value, dict):
        raise TemplateError("模板填充模式格式无效。")
    result = value.get("fit", "cover")
    if result not in REGION_FIT_MODES:
        raise TemplateError("模板区域填充模式不受支持。")
    return result


def _blend_mode(value: Any) -> str:
    if not isinstance(value, dict):
        raise TemplateError("模板混合模式格式无效。")
    result = value.get("blend_mode", "normal")
    if result not in BLEND_MODES:
        raise TemplateError("模板混合模式不受支持。")
    return result


def _asset_path(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("assets/") or ".." in Path(value).parts:
        raise TemplateError("模板资源路径无效。")
    return value


def _read_asset(archive: zipfile.ZipFile, asset_path: str) -> bytes:
    info = archive.getinfo(asset_path)
    if info.file_size > MAX_ASSET_BYTES:
        raise TemplateError("模板中的图片资源过大。")
    data = archive.read(asset_path)
    _check_png_dimensions(data)
    return data


def _check_png_dimensions(data: bytes) -> None:
    """Reject PNG assets whose announced dimensions exceed the canvas budget.

    The check runs on the header before the image is decoded, so a malicious
    template cannot force a large allocation merely to be rejected later.
    """
    if not data.startswith(_PNG_SIGNATURE) or len(data) < 24 or data[12:16] != b"IHDR":
        return
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width > 0 and height > 0 and width * height > MAX_CANVAS_PIXELS:
        raise TemplateError("模板中的 PNG 图片尺寸超过安全上限。")
