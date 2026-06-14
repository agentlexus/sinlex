"""Коэффициенты критериев изготовления по чертежу (CR-1, калибровка через env)."""

import os

COSTING_CRITERIA_VERSION = int(os.environ.get("SINLEX_COSTING_CRITERIA_VERSION", "1"))

RA_FINISH_THRESHOLD_MM = 1.6

CUT_MULT = float(os.environ.get("SINLEX_DRAW_CRIT_CUT_MULT", "1.15"))
SETUP_MULT = float(os.environ.get("SINLEX_DRAW_CRIT_SETUP_MULT", "1.20"))
CAM_MULT = float(os.environ.get("SINLEX_DRAW_CRIT_CAM_MULT", "1.25"))
SETUP_ADD_H = float(os.environ.get("SINLEX_DRAW_CRIT_SETUP_ADD_H", "0.4"))
MEASURE_PER_PART_H = float(os.environ.get("SINLEX_DRAW_CRIT_MEASURE_H", "0.25"))
GRIND_PRICE_MULT = float(os.environ.get("SINLEX_DRAW_CRIT_GRIND_PRICE_MULT", "1.35"))
THREAD_CAM_H = float(os.environ.get("SINLEX_DRAW_CRIT_THREAD_CAM_H", "0.35"))
KEYWAY_CAM_H = float(os.environ.get("SINLEX_DRAW_CRIT_KEYWAY_CAM_H", "1.0"))

GRINDING_OPERATION = "Шлифование"

KEYWAY_WIDTH_MIN_MM = 3.0
KEYWAY_WIDTH_MAX_MM = 20.0
