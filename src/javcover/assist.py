from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from javcover.models import Rect
from javcover.tasks import TaskCancelled


def suggest_color_blocks(image: QImage) -> list[Rect]:
    """Suggest rectangular panels from strong image-wide color transitions."""
    sample = image.scaled(
        320,
        320,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(
        QImage.Format.Format_RGB32
    )
    if sample.isNull():
        return []
    vertical = _transition_peaks(sample, vertical=True)
    horizontal = _transition_peaks(sample, vertical=False)
    if not vertical and not horizontal:
        return []
    x_cuts = [
        0,
        *(_scale_cut(value, sample.width(), image.width()) for value in vertical),
        image.width(),
    ]
    y_cuts = [
        0,
        *(_scale_cut(value, sample.height(), image.height()) for value in horizontal),
        image.height(),
    ]
    x_cuts = sorted(set(x_cuts))
    y_cuts = sorted(set(y_cuts))
    return [
        Rect(left, top, right - left, bottom - top)
        for top, bottom in zip(y_cuts, y_cuts[1:])
        for left, right in zip(x_cuts, x_cuts[1:])
        if right - left >= 8 and bottom - top >= 8
    ]


def _transition_peaks(image: QImage, *, vertical: bool) -> list[int]:
    span = image.width() if vertical else image.height()
    depth = image.height() if vertical else image.width()
    if span < 3:
        return []
    profiles: list[tuple[float, int]] = []
    for position in range(1, span - 1):
        difference = 0.0
        for offset in range(depth):
            first = (
                image.pixel(position - 1, offset)
                if vertical
                else image.pixel(offset, position - 1)
            )
            second = (
                image.pixel(position, offset)
                if vertical
                else image.pixel(offset, position)
            )
            difference += sum(
                abs(((first >> shift) & 0xFF) - ((second >> shift) & 0xFF))
                for shift in (16, 8, 0)
            )
        profiles.append((difference / depth, position))
    if not profiles:
        return []
    peak_threshold = max(30.0, max(score for score, _ in profiles) * 0.28)
    candidates = sorted(
        ((score, position) for score, position in profiles if score >= peak_threshold),
        reverse=True,
    )
    selected: list[int] = []
    minimum_gap = max(8, span // 12)
    for _, position in candidates:
        if all(abs(position - existing) >= minimum_gap for existing in selected):
            selected.append(position)
            if len(selected) == 2:
                break
    return sorted(selected)


def _scale_cut(position: int, source_span: int, target_span: int) -> int:
    return min(target_span - 1, max(1, round(position * target_span / source_span)))


def resolve_tesseract(executable: str | None = None) -> str:
    if executable:
        path = Path(executable).expanduser()
        if path.is_file():
            return str(path)
        raise RuntimeError(f"找不到已配置的 Tesseract 程序：{path}")
    discovered = shutil.which("tesseract")
    if discovered:
        return discovered
    for candidate in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Tesseract-OCR"
        / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Tesseract-OCR"
        / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Tesseract-OCR"
        / "tesseract.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        "没有找到 Tesseract OCR 程序。请安装 Tesseract（UB Mannheim Windows 版），"
        "然后在“工具 → OCR 设置”中选择 tesseract.exe。"
    )


def list_tesseract_languages(
    executable: str | None = None,
    tessdata_dir: str | None = None,
) -> set[str]:
    command = [resolve_tesseract(executable)]
    if tessdata_dir:
        directory = Path(tessdata_dir).expanduser()
        if not directory.is_dir():
            raise RuntimeError(f"找不到 Tesseract 语言数据目录：{directory}")
        command.extend(("--tessdata-dir", str(directory)))
    command.append("--list-langs")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("检查 Tesseract 语言数据超时。") from error
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"无法读取 Tesseract 语言数据：{detail}")
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if re.fullmatch(r"[A-Za-z0-9_]+", line.strip())
    }


def recognize_japanese_text(
    image: QImage,
    executable: str | None = None,
    tessdata_dir: str | None = None,
    cancel_event: object = None,
) -> list[tuple[Rect, str]]:
    binary = resolve_tesseract(executable)
    languages = list_tesseract_languages(binary, tessdata_dir)
    missing = {"jpn", "eng"} - languages
    if missing:
        needed = ", ".join(sorted(missing))
        configured = f"当前目录：{tessdata_dir}" if tessdata_dir else "当前 Tesseract 安装目录"
        raise RuntimeError(
            f"{configured} 缺少语言数据：{needed}。请在“工具 → OCR 设置”指定包含 "
            "jpn.traineddata 和 eng.traineddata 的 tessdata 文件夹。"
        )
    if cancel_event is not None and cancel_event.is_set():
        raise TaskCancelled()
    with tempfile.TemporaryDirectory(prefix="javcover-ocr-") as directory:
        image_path = Path(directory) / "source.png"
        if not image.save(str(image_path), "PNG"):
            raise RuntimeError("无法为 OCR 创建临时图片。")
        command = [
            binary,
            *(["--tessdata-dir", tessdata_dir] if tessdata_dir else []),
            str(image_path),
            "stdout",
            "-l",
            "jpn+eng",
            "tsv",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + 120
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event is not None and cancel_event.is_set():
                        process.kill()
                        process.communicate()
                        raise TaskCancelled()
                    if time.monotonic() > deadline:
                        process.kill()
                        process.communicate()
                        raise RuntimeError("OCR 超过 120 秒，已停止本次识别。")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    if process.returncode:
        detail = (stderr or "").strip() or f"Tesseract 返回代码 {process.returncode}"
        raise RuntimeError(f"OCR 识别失败：{detail}")
    recognized: list[tuple[Rect, str]] = []
    for row in csv.DictReader((stdout or "").splitlines(), delimiter="\t"):
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf", "-1"))
            left = int(row["left"])
            top = int(row["top"])
            width = int(row["width"])
            height = int(row["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if text and confidence >= 0 and width > 0 and height > 0:
            recognized.append((Rect(left, top, width, height), text))
    return recognized
