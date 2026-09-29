from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

MAX_CANVAS_PIXELS = 100_000_000
REGION_FIT_MODES = ("cover", "contain", "stretch")
BLEND_MODES = ("normal", "multiply", "screen", "overlay", "darken", "lighten", "add")
CANVAS_SHAPES = ("rect", "disc")


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @classmethod
    def from_points(cls, x1: int, y1: int, x2: int, y2: int) -> Rect:
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        return cls(left, top, right - left, bottom - top)

    def bounded(self, canvas_width: int, canvas_height: int) -> Rect:
        width = min(max(1, self.width), canvas_width)
        height = min(max(1, self.height), canvas_height)
        x = min(max(0, self.x), canvas_width - width)
        y = min(max(0, self.y), canvas_height - height)
        return Rect(x, y, width, height)

    def bounded_within(self, outer: Rect) -> Rect:
        """Clamp this rect so it stays inside ``outer`` (used for linked layers)."""
        width = min(max(1, self.width), outer.width)
        height = min(max(1, self.height), outer.height)
        x = min(max(outer.x, self.x), outer.x + outer.width - width)
        y = min(max(outer.y, self.y), outer.y + outer.height - height)
        return Rect(x, y, width, height)


@dataclass(slots=True)
class Region:
    rect: Rect
    name: str
    id: str = field(default_factory=lambda: uuid4().hex)
    background_png: bytes | None = None
    locked: bool = False
    visible: bool = True
    opacity: int = 100
    fit: str = "cover"
    blend_mode: str = "normal"
    bg_dx: int = 0
    bg_dy: int = 0


@dataclass(slots=True)
class DesignElement:
    kind: Literal["image", "text"]
    x: int
    y: int
    width: int
    height: int
    name: str
    id: str = field(default_factory=lambda: uuid4().hex)
    png: bytes | None = None
    text: str = ""
    font_family: str = "Yu Gothic UI"
    font_size: int = 48
    color: str = "#ffffff"
    outline_color: str = "#10131b"
    outline_width: int = 0
    bold: bool = False
    italic: bool = False
    vertical: bool = False
    locked: bool = False
    visible: bool = True
    opacity: int = 100
    blend_mode: str = "normal"
    region_id: str | None = None
    asset_name: str | None = None
    asset_kind: str | None = None
    asset_hash: str | None = None

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.width, self.height)

    @rect.setter
    def rect(self, value: Rect) -> None:
        self.x, self.y, self.width, self.height = (
            value.x,
            value.y,
            value.width,
            value.height,
        )


@dataclass(frozen=True, slots=True)
class Guide:
    axis: Literal["x", "y"]
    position: int
    name: str = ""


@dataclass(slots=True)
class Project:
    width: int
    height: int
    base_png: bytes | None = None
    regions: list[Region] = field(default_factory=list)
    guides: list[Guide] = field(default_factory=list)
    elements: list[DesignElement] = field(default_factory=list)
    shape: str = "rect"

    def add_region(self, rect: Rect) -> Region:
        region = Region(rect=rect, name=f"区域 {len(self.regions) + 1}")
        self.regions.append(region)
        return region


def snap_rect(
    rect: Rect,
    canvas_width: int,
    canvas_height: int,
    guides: list[Guide],
    other_rects: list[Rect],
    threshold: int,
    grid_size: int = 0,
) -> Rect:
    """Snap a rectangle's position to nearby canvas, guide, region, or grid lines."""
    x_targets = {0, canvas_width}
    y_targets = {0, canvas_height}
    for guide in guides:
        (x_targets if guide.axis == "x" else y_targets).add(guide.position)
    for other in other_rects:
        x_targets.update((other.x, other.center_x, other.right))
        y_targets.update((other.y, other.center_y, other.bottom))

    def nearest_delta(edges: tuple[int, ...], targets: set[int]) -> int:
        candidates = [
            (target - edge, abs(target - edge))
            for edge in edges
            for target in targets
            if abs(target - edge) <= threshold
        ]
        if grid_size > 0:
            for edge in edges:
                target = round(edge / grid_size) * grid_size
                if abs(target - edge) <= threshold:
                    candidates.append((target - edge, abs(target - edge)))
        return min(candidates, key=lambda value: value[1])[0] if candidates else 0

    dx = nearest_delta((rect.x, rect.center_x, rect.right), x_targets)
    dy = nearest_delta((rect.y, rect.center_y, rect.bottom), y_targets)
    return Rect(rect.x + dx, rect.y + dy, rect.width, rect.height).bounded(
        canvas_width, canvas_height
    )
