"""Shared task primitives (no Qt imports, safe to use anywhere)."""

from __future__ import annotations


class TaskCancelled(Exception):
    """Raised when a background task is cancelled by the user."""
