import unittest

from javcover.models import Guide, Rect, snap_rect


class RectTests(unittest.TestCase):
    def test_normalizes_drag_direction(self) -> None:
        self.assertEqual(Rect.from_points(30, 40, 10, 5), Rect(10, 5, 20, 35))

    def test_bounds_rect_without_changing_its_size_when_possible(self) -> None:
        self.assertEqual(Rect(-8, 90, 30, 20).bounded(100, 100), Rect(0, 80, 30, 20))

    def test_oversized_rect_is_clamped_to_canvas(self) -> None:
        self.assertEqual(Rect(0, 0, 200, 120).bounded(100, 80), Rect(0, 0, 100, 80))

    def test_bounded_within_keeps_rect_inside_outer(self) -> None:
        outer = Rect(10, 20, 100, 50)
        self.assertEqual(Rect(0, 0, 200, 200).bounded_within(outer), outer)
        self.assertEqual(
            Rect(200, 200, 30, 20).bounded_within(outer), Rect(80, 50, 30, 20)
        )


class SnapTests(unittest.TestCase):
    def test_snaps_position_to_guide_and_other_region(self) -> None:
        actual = snap_rect(
            Rect(93, 42, 40, 30),
            300,
            200,
            [Guide("x", 100), Guide("y", 50)],
            [Rect(180, 70, 40, 30)],
            threshold=8,
        )
        self.assertEqual(actual, Rect(100, 40, 40, 30))

    def test_does_not_snap_outside_threshold(self) -> None:
        actual = snap_rect(Rect(90, 90, 20, 20), 300, 200, [], [], threshold=4)
        self.assertEqual(actual, Rect(90, 90, 20, 20))

    def test_snaps_to_grid(self) -> None:
        actual = snap_rect(Rect(31, 47, 18, 20), 200, 200, [], [], 3, grid_size=16)
        self.assertEqual(actual, Rect(32, 48, 18, 20))


if __name__ == "__main__":
    unittest.main()
