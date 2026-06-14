"""Диск/корпус с фасонным наружным контуром: Ø прутка по огибающей bbox."""

import unittest

from extraction_tool.extractor import (
    _bbox_axis_profile,
    _refine_rod_diameter,
    _rod_dims_from_bbox,
)


class TestDiscRodDiameter(unittest.TestCase):
    def test_refine_keeps_bbox_for_disc_octagon(self):
        axis = _bbox_axis_profile({"x": 173.7, "y": 8.0, "z": 173.7})
        self.assertTrue(axis["is_disc"])
        d_geom = 173.7
        shafts = [{"diameter": 60.0}, {"diameter": 54.5}]
        self.assertEqual(_refine_rod_diameter(d_geom, shafts, axis=axis), d_geom)

    def test_refine_still_clamps_inflated_bar_bbox(self):
        axis = _bbox_axis_profile({"x": 52.0, "y": 52.0, "z": 300.0})
        self.assertTrue(axis["is_elongated_rod"])
        shafts = [{"diameter": 50.0}]
        self.assertEqual(_refine_rod_diameter(80.0, shafts, axis=axis), 50.0)

    def test_rod_dims_from_bbox_disc(self):
        d, ln = _rod_dims_from_bbox({"x": 173.7, "y": 8.0, "z": 173.7})
        self.assertAlmostEqual(d, 173.7, places=1)
        self.assertAlmostEqual(ln, 8.0, places=1)


if __name__ == "__main__":
    unittest.main()
