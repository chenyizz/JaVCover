import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from javcover.core.models import DesignElement, Guide, Project, Rect, Region
from javcover.services.template_io import TemplateError, load_project, save_project


class TemplateIoTests(unittest.TestCase):
    def test_reads_version_one_projects_without_design_elements(self) -> None:
        manifest = {
            "format_version": 1,
            "canvas": {"width": 80, "height": 60},
            "base_image": None,
            "regions": [],
            "guides": [{"axis": "x", "position": 12}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(manifest))
            restored = load_project(path)
        self.assertEqual((restored.width, restored.height), (80, 60))
        self.assertEqual(restored.guides, [Guide("x", 12)])
        self.assertEqual(restored.elements, [])

    def test_round_trips_project_and_embedded_assets(self) -> None:
        project = Project(
            width=640,
            height=480,
            base_png=b"base image bytes",
            regions=[
                Region(
                    rect=Rect(10, 20, 300, 200),
                    name="封面",
                    id="0123456789abcdef0123456789abcdef",
                    background_png=b"region image bytes",
                    lock="full",
                    visible=False,
                )
            ],
            guides=[Guide("x", 320), Guide("y", 240)],
            elements=[
                DesignElement(
                    kind="image",
                    x=5,
                    y=6,
                    width=12,
                    height=9,
                    name="logo",
                    id="abcdef0123456789abcdef0123456789",
                    png=b"embedded logo",
                ),
                DesignElement(
                    kind="text",
                    x=30,
                    y=40,
                    width=200,
                    height=70,
                    name="title",
                    id="abcdef0123456789abcdef0123456788",
                    text="作品タイトル",
                    font_family="Yu Gothic UI",
                    font_size=56,
                    color="#ffcc00",
                    outline_color="#111111",
                    outline_width=3,
                    bold=True,
                    vertical=True,
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.javcover"
            save_project(project, path)
            restored = load_project(path)
        self.assertEqual(restored.width, project.width)
        self.assertEqual(restored.height, project.height)
        self.assertEqual(restored.base_png, project.base_png)
        self.assertEqual(restored.regions, project.regions)
        self.assertEqual(restored.regions[0].lock, "full")
        self.assertFalse(restored.regions[0].visible)
        self.assertEqual(restored.guides, project.guides)
        self.assertEqual(restored.elements, project.elements)

    def test_rejects_unsupported_template_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsupported.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps({"format_version": 999}))
            with self.assertRaises(TemplateError):
                load_project(path)

    def test_rejects_region_outside_canvas(self) -> None:
        manifest = {
            "format_version": 1,
            "canvas": {"width": 100, "height": 100},
            "base_image": None,
            "regions": [
                {
                    "id": "0123456789abcdef0123456789abcdef",
                    "name": "bad",
                    "rect": {"x": 90, "y": 0, "width": 20, "height": 20},
                    "background_image": None,
                }
            ],
            "guides": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outside.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(manifest))
            with self.assertRaisesRegex(TemplateError, "超出画布"):
                load_project(path)

    def test_round_trips_asset_backed_element(self) -> None:
        project = Project(
            width=100,
            height=80,
            elements=[
                DesignElement(
                    kind="image",
                    x=1,
                    y=2,
                    width=10,
                    height=8,
                    name="title-art",
                    id="abcdef0123456789abcdef0123456788",
                    png=b"rasterized title",
                    asset_name="0011aabb_title.psd",
                    asset_kind="psd",
                    asset_hash="deadbeef",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.javcover"
            save_project(project, path)
            restored = load_project(path)
        element = restored.elements[0]
        self.assertEqual(element.asset_name, "0011aabb_title.psd")
        self.assertEqual(element.asset_kind, "psd")
        self.assertEqual(element.asset_hash, "deadbeef")
        self.assertEqual(element.png, b"rasterized title")

    def test_rejects_asset_name_with_path_separator(self) -> None:
        manifest = {
            "format_version": 3,
            "canvas": {"width": 100, "height": 100},
            "base_image": None,
            "regions": [],
            "guides": [],
            "elements": [
                {
                    "id": "abcdef0123456789abcdef0123456788",
                    "kind": "text",
                    "name": "t",
                    "rect": {"x": 0, "y": 0, "width": 10, "height": 10},
                    "image": None,
                    "asset_name": "../evil.png",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trav.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(manifest))
            with self.assertRaisesRegex(TemplateError, "素材名称"):
                load_project(path)

    def test_round_trips_region_and_element_style_fields(self) -> None:
        region = Region(
            rect=Rect(0, 0, 10, 10),
            name="r",
            opacity=40,
            fit="contain",
            blend_mode="multiply",
            lock="full",
            visible=False,
        )
        project = Project(
            width=50,
            height=50,
            regions=[region],
            elements=[
                DesignElement(
                    kind="text",
                    x=0,
                    y=0,
                    width=5,
                    height=5,
                    name="t",
                    id="abcdef0123456789abcdef0123456788",
                    text="a",
                    locked=True,
                    visible=False,
                    opacity=30,
                    blend_mode="screen",
                    region_id=region.id,
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "styles.javcover"
            save_project(project, path)
            restored = load_project(path)
        self.assertEqual(restored.regions[0].opacity, 40)
        self.assertEqual(restored.regions[0].fit, "contain")
        self.assertEqual(restored.regions[0].blend_mode, "multiply")
        self.assertEqual(restored.regions[0].lock, "full")
        self.assertFalse(restored.regions[0].visible)
        element = restored.elements[0]
        self.assertEqual(element.opacity, 30)
        self.assertEqual(element.blend_mode, "screen")
        self.assertEqual(element.region_id, region.id)
        self.assertTrue(element.locked)
        self.assertFalse(element.visible)

    def test_version_three_defaults_new_fields(self) -> None:
        manifest = {
            "format_version": 3,
            "canvas": {"width": 100, "height": 100},
            "base_image": None,
            "regions": [
                {
                    "id": "0123456789abcdef0123456789abcdef",
                    "name": "cover",
                    "rect": {"x": 0, "y": 0, "width": 50, "height": 50},
                    "background_image": None,
                }
            ],
            "guides": [],
            "elements": [
                {
                    "id": "abcdef0123456789abcdef0123456788",
                    "kind": "text",
                    "name": "title",
                    "rect": {"x": 0, "y": 0, "width": 10, "height": 10},
                    "text": "x",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v3.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(manifest))
            restored = load_project(path)
        self.assertEqual(restored.regions[0].opacity, 100)
        self.assertEqual(restored.regions[0].fit, "cover")
        self.assertEqual(restored.regions[0].blend_mode, "normal")
        self.assertFalse(restored.elements[0].locked)
        self.assertTrue(restored.elements[0].visible)
        self.assertEqual(restored.elements[0].opacity, 100)
        self.assertEqual(restored.elements[0].blend_mode, "normal")
        self.assertIsNone(restored.elements[0].region_id)

    def test_round_trips_canvas_shape_and_background_offset(self) -> None:
        project = Project(
            width=200,
            height=200,
            shape="disc",
            regions=[
                Region(
                    rect=Rect(0, 0, 50, 50),
                    name="盘面",
                    bg_dx=7,
                    bg_dy=-9,
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disc.javcover"
            save_project(project, path)
            restored = load_project(path)
        self.assertEqual(restored.shape, "disc")
        self.assertEqual(restored.regions[0].bg_dx, 7)
        self.assertEqual(restored.regions[0].bg_dy, -9)

    def test_round_trips_named_guides(self) -> None:
        project = Project(
            width=100,
            height=100,
            guides=[Guide("x", 30, "中缝"), Guide("y", 50)],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guides.javcover"
            save_project(project, path)
            restored = load_project(path)
        self.assertEqual(restored.guides[0], Guide("x", 30, "中缝"))
        self.assertEqual(restored.guides[1].name, "")

    def test_failed_save_leaves_no_temporary_files(self) -> None:
        project = Project(width=10, height=10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.javcover"
            with patch(
                "javcover.services.template_io.zipfile.ZipFile",
                side_effect=ValueError("archive failure"),
            ):
                with self.assertRaises(ValueError):
                    save_project(project, path)
            leftovers = [entry for entry in Path(directory).iterdir() if entry.suffix == ".tmp"]
            self.assertEqual(leftovers, [])

    def test_rejects_png_asset_with_excessive_dimensions(self) -> None:
        header = (
            b"\x89PNG\r\n\x1a\n"
            + (13).to_bytes(4, "big")
            + b"IHDR"
            + (20000).to_bytes(4, "big")
            + (20000).to_bytes(4, "big")
            + bytes(8)
        )
        manifest = {
            "format_version": 2,
            "canvas": {"width": 100, "height": 100},
            "base_image": "assets/base.png",
            "regions": [],
            "guides": [],
            "elements": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "huge-png.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(manifest))
                archive.writestr("assets/base.png", header)
            with self.assertRaisesRegex(TemplateError, "PNG"):
                load_project(path)

    def test_old_region_fields_default_to_unlocked_and_visible(self) -> None:
        manifest = {
            "format_version": 1,
            "canvas": {"width": 100, "height": 100},
            "base_image": None,
            "regions": [
                {
                    "id": "0123456789abcdef0123456789abcdef",
                    "name": "cover",
                    "rect": {"x": 0, "y": 0, "width": 50, "height": 50},
                    "background_image": None,
                }
            ],
            "guides": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-region.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(manifest))
            restored = load_project(path)
        self.assertEqual(restored.regions[0].lock, "none")
        self.assertTrue(restored.regions[0].visible)

    def test_version_seven_boolean_lock_maps_to_full_lock(self) -> None:
        manifest = {
            "format_version": 7,
            "canvas": {"width": 100, "height": 100},
            "base_image": None,
            "regions": [
                {
                    "id": "0123456789abcdef0123456789abcdef",
                    "name": "cover",
                    "rect": {"x": 0, "y": 0, "width": 50, "height": 50},
                    "background_image": None,
                    "locked": True,
                },
                {
                    "id": "abcdef0123456789abcdef0123456789",
                    "name": "back",
                    "rect": {"x": 50, "y": 0, "width": 50, "height": 50},
                    "background_image": None,
                    "locked": False,
                },
            ],
            "guides": [],
            "elements": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v7-lock.javcover"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("project.json", json.dumps(manifest))
            restored = load_project(path)
        self.assertEqual(restored.regions[0].lock, "full")
        self.assertTrue(restored.regions[0].locked)
        self.assertTrue(restored.regions[0].content_locked)
        self.assertEqual(restored.regions[1].lock, "none")
        self.assertFalse(restored.regions[1].locked)


if __name__ == "__main__":
    unittest.main()
