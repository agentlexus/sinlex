"""Классификация сложности: detail_index для мелких деталей, sa/v для крупных."""

import unittest

from extraction_tool.extractor import _classify_complexity_hint, _complexity_metrics


class TestClassifyComplexityHint(unittest.TestCase):
    def test_stud_hex_low_not_high(self):
        c = _classify_complexity_hint(
            detail_index=8.88,
            sa_v=1.66,
            volume_mm3=153.0,
            face_count=41,
            part_family="rod",
            hex_head_stud=True,
        )
        self.assertEqual(c, "низкая")

    def test_large_part_sa_v_high_unchanged(self):
        c = _classify_complexity_hint(
            detail_index=13.0,
            sa_v=0.35,
            volume_mm3=100_000.0,
            face_count=80,
            part_family="plate",
        )
        self.assertEqual(c, "высокая")

    def test_large_part_sa_v_medium_unchanged(self):
        c = _classify_complexity_hint(
            detail_index=16.5,
            sa_v=0.25,
            volume_mm3=200_000.0,
            face_count=80,
            part_family="plate",
        )
        self.assertEqual(c, "средняя")

    def test_small_cube_not_high_from_sa_v(self):
        c = _classify_complexity_hint(
            detail_index=6.0,
            sa_v=0.6,
            volume_mm3=1000.0,
            face_count=12,
            part_family="plate",
        )
        self.assertEqual(c, "низкая")

    def test_detail_index_17_still_high(self):
        c = _classify_complexity_hint(
            detail_index=18.0,
            sa_v=0.05,
            volume_mm3=1_000_000.0,
            face_count=50,
            part_family="plate",
        )
        self.assertEqual(c, "высокая")

    def test_sleeve_face_count_medium(self):
        c = _classify_complexity_hint(
            detail_index=11.5,
            sa_v=0.22,
            volume_mm3=185_000.0,
            face_count=123,
            part_family="rod",
        )
        self.assertEqual(c, "средняя")

    def test_hybrid_shaft_high(self):
        c = _classify_complexity_hint(
            detail_index=5.0,
            sa_v=0.1,
            volume_mm3=50_000.0,
            face_count=20,
            part_family="hybrid_shaft",
        )
        self.assertEqual(c, "высокая")

    def test_complexity_metrics_stud(self):
        m = _complexity_metrics(
            153.0,
            254.4,
            {"x": 5.77, "y": 12.5, "z": 5.77},
            {"face_count": 41},
            {"cyl_face_count": 6, "plane_face_count": 9},
            part_family="rod",
            hex_head_stud=True,
        )
        self.assertEqual(m["complexity_hint"], "низкая")
        self.assertAlmostEqual(m["detail_index"], 8.88, delta=0.05)


if __name__ == "__main__":
    unittest.main()
