from __future__ import annotations

_BLEND_MODE_LABELS = {
    "normal": "正常",
    "multiply": "正片叠底",
    "screen": "滤色",
    "overlay": "叠加",
    "darken": "变暗",
    "lighten": "变亮",
    "add": "线性减淡",
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".psd"}


def format_output_name(pattern: str, stem: str, index: int, date_token: str) -> str:
    """Expand batch-export filename placeholders: {name}, {index}, {date}."""
    return (
        pattern.replace("{name}", stem)
        .replace("{index}", f"{index:03d}")
        .replace("{date}", date_token)
    )


