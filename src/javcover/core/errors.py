"""Shared application errors (kept dependency-free to avoid import cycles)."""

from __future__ import annotations


class ImageError(ValueError):
    """Raised when an image cannot be decoded, encoded, composed or cropped."""
