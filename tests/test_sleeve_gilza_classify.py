"""Гильза МФСУ.387441.001-01: синтетика по метрикам STEP (без STP в git).

Эталонные метрики получены локально из
D:\\ИП\\SINLEX.TECH\\test\\гильза\\МФСУ.387441.001-01_Гильза свечи зажигания.stp
"""

import unittest

from extraction_tool import config
from extraction_tool.extractor import (
    _bbox_axis_profile,
    _detect_part_family,
    _evaluate_turning_case,
    _infer_processes,
    _is_impeller_family,
    _resolve_part_family,
)

# Метрики гильзы (fast-анализ, ~123 грани)
SLEEVE_BBOX = {"x": 52.56, "y": 148.02, "z": 56.54}
SLEEVE_FC = {
    "cyl_face_count": 35,
    "plane_face_count": 19,
    "torus_face_count": 32,
    "cone_face_count": 38,
    "other_face_count": 0,
    "sphere_face_count": 0,
}
SLEEVE_TOPO = {"face_count": 123}
SLEEVE_DETAIL_INDEX = 11.5
SLEEVE_VOLUME_MM3 = 185_000.0

SLEEVE_ROT_PROFILE = {
    "rotation_confidence": 0.72,
    "outer_diameter_mm": 56.5,
    "ld_ratio": 2.62,
    "outer_cyl_area_share": 0.48,
    "plane_penalty": 0.22,
    "rotational": False,
}


class TestSleeveGilzaClassify(unittest.TestCase):
    def test_bbox_is_elongated_rod(self):
        axis = _bbox_axis_profile(SLEEVE_BBOX)
        self.assertTrue(axis["is_elongated_rod"])
        self.assertTrue(axis["cross_round"])
        self.assertGreater(axis["elongation"], 2.5)

    def test_not_impeller_despite_torus_fillets(self):
        self.assertFalse(
            _is_impeller_family(
                SLEEVE_FC,
                SLEEVE_TOPO,
                bbox=SLEEVE_BBOX,
                detail_index=SLEEVE_DETAIL_INDEX,
            )
        )

    def test_detect_and_resolve_rod(self):
        detected = _detect_part_family(
            SLEEVE_FC,
            SLEEVE_BBOX,
            SLEEVE_TOPO,
            detail_index=SLEEVE_DETAIL_INDEX,
        )
        self.assertEqual(detected, "rod")
        resolved = _resolve_part_family(
            SLEEVE_FC,
            SLEEVE_BBOX,
            SLEEVE_TOPO,
            detail_index=SLEEVE_DETAIL_INDEX,
            volume_mm3=SLEEVE_VOLUME_MM3,
        )
        self.assertEqual(resolved, "rod")

    def test_turning_bar_case(self):
        case, rotational, skip = _evaluate_turning_case(
            SLEEVE_ROT_PROFILE,
            SLEEVE_BBOX,
            part_family="rod",
        )
        self.assertEqual(case, "bar")
        self.assertTrue(rotational)
        self.assertIsNone(skip)

    def test_processes_include_turning(self):
        rot = dict(SLEEVE_ROT_PROFILE)
        rot["rotational"] = True
        processes = _infer_processes(
            SLEEVE_FC,
            SLEEVE_BBOX,
            part_family="rod",
            rot_profile=rot,
            rod_meta={"holes_feature_count": 0},
        )
        self.assertIn("Токарная", processes)


class TestImpellerStillRecognized(unittest.TestCase):
    """Регрессия: настоящая крыльчатка не должна стать rod."""

    IMP_BBOX = {"x": 126.8, "y": 275.4, "z": 275.9}
    IMP_FC = {
        "cyl_face_count": 21,
        "plane_face_count": 30,
        "torus_face_count": 222,
        "other_face_count": 408,
        "cone_face_count": 0,
        "sphere_face_count": 0,
    }
    IMP_TOPO = {"face_count": 721}

    def test_impeller_family(self):
        self.assertTrue(
            _is_impeller_family(
                self.IMP_FC,
                self.IMP_TOPO,
                bbox=self.IMP_BBOX,
                detail_index=22.0,
            )
        )

    def test_resolve_stays_impeller(self):
        resolved = _resolve_part_family(
            self.IMP_FC,
            self.IMP_BBOX,
            self.IMP_TOPO,
            detail_index=22.0,
            volume_mm3=347_037.0,
        )
        self.assertEqual(resolved, "impeller")


if __name__ == "__main__":
    unittest.main()
