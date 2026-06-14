"""Вероятностный гейт ray-casting тонкостенности в fast-режиме."""

import unittest

from extraction_tool import config
from extraction_tool.extractor import (
    _resolve_part_family,
    _wall_thickness_run_probability,
)


class TestWallThicknessGate(unittest.TestCase):
    def test_impeller_not_downgraded_to_rod(self):
        bbox = {"x": 126.8, "y": 275.4, "z": 275.9}
        topo = {"face_count": 721}
        fc = {
            "cyl_face_count": 21,
            "plane_face_count": 30,
            "torus_face_count": 222,
            "other_face_count": 408,
        }
        base = "impeller"
        resolved = _resolve_part_family(fc, bbox, topo, detail_index=22.0, volume_mm3=3e5)
        self.assertEqual(resolved, "impeller")

    def test_housing_disc_high_probability(self):
        p = _wall_thickness_run_probability(
            surface_to_volume_ratio=0.90,
            detail_index=32.8,
            part_family="rod",
            base_family="rod",
            bbox={"x": 173.7, "y": 8.0, "z": 173.7},
            face_counts={"cyl_face_count": 256, "plane_face_count": 143, "torus_face_count": 0, "other_face_count": 16},
            topo={"face_count": 415},
            rot_profile={"rotation_confidence": 0.78},
            volume_mm3=48476.0,
        )
        self.assertGreaterEqual(p, config.WALL_THICKNESS_RUN_THRESHOLD)

    def test_elongated_shaft_low_probability(self):
        p = _wall_thickness_run_probability(
            surface_to_volume_ratio=0.11,
            detail_index=19.5,
            part_family="oversize",
            base_family="hybrid_shaft",
            bbox={"x": 1120.0, "y": 97.0, "z": 134.0},
            face_counts={"cyl_face_count": 121, "plane_face_count": 91},
            topo={"face_count": 313},
            rot_profile={"rotation_confidence": 0.15},
            hybrid_turn_mill=True,
            volume_mm3=4.9e6,
        )
        self.assertEqual(p, 0.0)

    def test_turning_bar_low_probability(self):
        p = _wall_thickness_run_probability(
            surface_to_volume_ratio=0.12,
            detail_index=10.0,
            part_family="rod",
            base_family="rod",
            bbox={"x": 50.0, "y": 50.0, "z": 300.0},
            face_counts={"cyl_face_count": 18, "plane_face_count": 8},
            topo={"face_count": 40},
            rot_profile={"rotation_confidence": 0.85},
            volume_mm3=5e5,
        )
        self.assertLess(p, config.WALL_THICKNESS_RUN_THRESHOLD)

    def test_impeller_moderate_sa_v_still_runs(self):
        p = _wall_thickness_run_probability(
            surface_to_volume_ratio=0.32,
            detail_index=22.2,
            part_family="impeller",
            base_family="impeller",
            bbox={"x": 126.8, "y": 275.4, "z": 275.9},
            face_counts={"cyl_face_count": 21, "plane_face_count": 30, "torus_face_count": 222, "other_face_count": 408},
            topo={"face_count": 721},
            rot_profile={"rotation_confidence": 0.59},
            volume_mm3=347037.0,
        )
        self.assertGreaterEqual(p, config.WALL_THICKNESS_RUN_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
