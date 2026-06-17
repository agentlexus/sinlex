"""Интерполяция серийности партии для произвольного количества шт."""
from machining_cost import BATCH_CUTTING_FACTOR, BATCH_SIZE_MAX, _interp_curve


def test_interp_curve_midpoint_between_anchor_points():
    # Между 1 и 10 шт — линейная интерполяция коэффициента резания.
    assert _interp_curve(5, BATCH_CUTTING_FACTOR) == 5 / 9 + 2 / 9  # 7/9


def test_interp_curve_clamps_to_batch_limits():
    assert _interp_curve(0, BATCH_CUTTING_FACTOR) == BATCH_CUTTING_FACTOR[1]
    assert _interp_curve(9999, BATCH_CUTTING_FACTOR) == BATCH_CUTTING_FACTOR[BATCH_SIZE_MAX]
