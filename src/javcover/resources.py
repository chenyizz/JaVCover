"""Locate bundled resources (icons) regardless of the running module."""

from __future__ import annotations

from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent / "icons"
