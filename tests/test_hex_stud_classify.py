"""STUD.122 — шпилька с шестигранником: токарка + фрезеровка головки."""

import unittest

from extraction_tool.extractor import (
    _bbox_axis_profile,
    _evaluate_turning_case,
    _infer_processes,
    _is_hex_head_stud,
)

STUD_BBOX = {"x": 5.7743, "y": 12.5008, "z": 5.7743}
STUD_FC = {
    "cyl_face_count": 6,
    "plane_face_count": 9,
    "torus_face_count": 0,
    "cone_face_count": 0,
    "other_face_count": 26,
    "sphere_face_count": 0,
}
STUD_ROT = {
    "rotation_confidence": 0.0,
    "outer_diameter_mm": 5.77,
    "ld_ratio": 2.1649,
    "outer_cyl_area_share": 0.0,
    "plane_penalty": 0.1537,
    "rotational": False,
}
STUD_SHAFTS = [{"diameter": 5.8, "radius": 2.9, "feature": "body"}]
STUD_HOLES = [
    {"diameter": 2.5, "radius": 1.2, "feature": "bore"},
    {"diameter": 2.5, "radius": 1.2, "feature": "bore"},
]


class TestHexStudClassify(unittest.TestCase):
    def test_detect_hex_stud_geometry(self):
        self.assertTrue(
            _is_hex_head_stud(
                STUD_ROT,
                STUD_BBOX,
                STUD_FC,
                STUD_SHAFTS,
                part_family="rod",
                part_name="STUD.122 шестигр",
            )
        )

    def test_turning_bar_case(self):
        case, rotational, skip = _evaluate_turning_case(
            STUD_ROT,
            STUD_BBOX,
            part_family="rod",
            part_name="STUD.122 шестигр",
            face_counts=STUD_FC,
            shafts=STUD_SHAFTS,
            hex_head_stud=True,
        )
        self.assertEqual(case, "bar")
        self.assertTrue(rotational)
        self.assertIsNone(skip)

    def test_processes_turn_and_mill_only(self):
        ops = _infer_processes(
            STUD_FC,
            STUD_BBOX,
            STUD_HOLES,
            STUD_SHAFTS,
            face_count=41,
            detail_index=8.88,
            part_family="rod",
            rod_meta={"hex_head_stud": True},
            rot_profile={**STUD_ROT, "rotational": True, "turning_case": "bar"},
            part_name="STUD.122 шестигр",
        )
        self.assertIn("Токарная", ops)
        self.assertIn("Фрезерная", ops)
        self.assertNotIn("Сверление", ops)
        self.assertEqual(ops.index("Токарная"), 0)

    def test_bbox_elongated_rod(self):
        axis = _bbox_axis_profile(STUD_BBOX)
        self.assertTrue(axis["is_elongated_rod"])
        self.assertAlmostEqual(axis["elongation"], 2.16, delta=0.05)


if __name__ == "__main__":
    unittest.main()
