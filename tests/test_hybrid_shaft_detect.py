"""Гибрид вал-корпус: токарка торцов + фрезер (вал намотки)."""

import unittest

from extraction_tool.extractor import (
    _infer_processes,
    _is_hybrid_turn_mill_body,
)


class TestHybridShaftDetect(unittest.TestCase):
    def test_winding_shaft_bbox_signature(self):
        bbox = {"x": 97.0, "y": 134.0, "z": 1120.0}
        fc = {
            "cyl_face_count": 121,
            "plane_face_count": 91,
            "torus_face_count": 20,
            "cone_face_count": 0,
            "sphere_face_count": 0,
            "other_face_count": 30,
        }
        self.assertTrue(
            _is_hybrid_turn_mill_body(fc, bbox, face_count=313, part_name="Вал_намотки.stp")
        )

    def test_processes_include_turning(self):
        bbox = {"x": 97.0, "y": 134.0, "z": 1120.0}
        fc = {
            "cyl_face_count": 121,
            "plane_face_count": 91,
            "torus_face_count": 20,
            "other_face_count": 30,
        }
        ops = _infer_processes(
            fc,
            bbox,
            [],
            [],
            face_count=313,
            detail_index=19.5,
            part_family="oversize",
            rod_meta={"hybrid_turn_mill": True},
        )
        self.assertIn("Токарная", ops)
        self.assertTrue(
            "Фрезерная" in ops or "Фрезерная (5-осевая)" in ops
        )

    def test_classic_rod_not_hybrid(self):
        bbox = {"x": 50.0, "y": 50.0, "z": 320.0}
        fc = {"cyl_face_count": 8, "plane_face_count": 2}
        self.assertFalse(_is_hybrid_turn_mill_body(fc, bbox, face_count=12))


if __name__ == "__main__":
    unittest.main()
