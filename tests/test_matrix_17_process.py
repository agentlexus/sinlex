"""Матрица 17: осевой карман Ø15 на прутке — только токарка."""

import unittest

from extraction_tool.extractor import (
    _infer_processes,
    _is_coaxial_bar_turning,
    _rod_blind_15_needs_milling,
)

MATRIX_BBOX = {"x": 16.0, "y": 49.0, "z": 16.0}
MATRIX_FC = {
    "cyl_face_count": 4,
    "plane_face_count": 4,
    "torus_face_count": 0,
    "cone_face_count": 2,
    "other_face_count": 3,
    "sphere_face_count": 0,
    "holes_count": 1,
}
MATRIX_ROT = {
    "rotation_confidence": 0.66,
    "outer_diameter_mm": 15.0,
    "ld_ratio": 3.2667,
    "outer_cyl_area_share": 0.4528,
    "plane_penalty": 0.0,
    "main_axis_coaxiality": 1.0,
    "rotational": True,
    "turning_case": "bar",
}
MATRIX_ROD_META = {
    "has_blind_15": True,
    "has_keyway": False,
    "has_m6": False,
    "holes_feature_count": 1,
}
MATRIX_HOLES = [
    {"diameter": 0.7, "radius": 0.35, "feature": "bore"},
    {"diameter": 8.0, "radius": 4.0, "feature": "bore"},
    {"diameter": 15.0, "radius": 7.5, "feature": "blind_hole"},
]
DISC_ROT = {
    "rotation_confidence": 0.7,
    "outer_diameter_mm": 200.0,
    "ld_ratio": 0.35,
    "main_axis_coaxiality": 0.75,
    "rotational": True,
    "turning_case": "disc",
}


class TestMatrix17Process(unittest.TestCase):
    def test_coaxial_bar_detected(self):
        self.assertTrue(_is_coaxial_bar_turning(MATRIX_ROT))

    def test_blind_15_not_milling_on_bar(self):
        self.assertFalse(_rod_blind_15_needs_milling(MATRIX_ROD_META, MATRIX_ROT))

    def test_blind_15_still_milling_on_disc(self):
        self.assertTrue(_rod_blind_15_needs_milling(MATRIX_ROD_META, DISC_ROT))

    def test_processes_turning_only(self):
        ops = _infer_processes(
            MATRIX_FC,
            MATRIX_BBOX,
            MATRIX_HOLES,
            [{"diameter": 15.0, "radius": 7.5, "feature": "body"}],
            face_count=13,
            detail_index=6.0,
            part_family="rod",
            rod_meta=MATRIX_ROD_META,
            rot_profile=MATRIX_ROT,
            part_name="Матрица_17",
        )
        self.assertEqual(ops, ["Токарная"])


if __name__ == "__main__":
    unittest.main()
