"""Build a multi-size Windows .ico from the app SVG using Qt (no extra deps).

Usage: python tools/make_icon.py <app-icon.svg> <out.ico>
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_svg(svg_path: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise SystemExit(f"无法解析 SVG：{svg_path}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise SystemExit("无法创建内存缓冲区")
    if not image.save(buffer, "PNG"):
        raise SystemExit("无法编码 PNG")
    buffer.close()
    return bytes(data)


def write_ico(path: Path, frames: list[tuple[int, bytes]]) -> None:
    count = len(frames)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    payload = b""
    offset = 6 + 16 * count
    for size, data in frames:
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
        payload += data
    path.write_bytes(header + entries + payload)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        raise SystemExit("usage: make_icon.py <app-icon.svg> <out.ico>")
    app = QGuiApplication.instance() or QGuiApplication([])
    svg_path = Path(argv[1])
    out_path = Path(argv[2])
    frames = [(size, png_bytes(render_svg(svg_path, size))) for size in SIZES]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_ico(out_path, frames)
    print(f"已生成图标：{out_path}（{len(frames)} 个尺寸）")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
