"""Конфигурация модуля глубокого извлечения данных из STEP."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# Папка с STEP для пакетной обработки (main.py)
STEP_INPUT_DIR = os.environ.get(
    "SINLEX_STEP_INPUT_DIR",
    os.path.join(PROJECT_ROOT, "projects"),
)

# SQLite-база метрик
DB_PATH = os.environ.get(
    "SINLEX_EXTRACTION_DB",
    os.path.join(BASE_DIR, "parts_metrics.db"),
)

# Примитивная цена: объём (мм³) × коэффициент → руб (для сравнения с ML-моделью)
PRICE_PER_MM3 = float(os.environ.get("SINLEX_PRICE_PER_MM3", "0.00008"))

# Этапы (можно отключать тяжёлые вычисления)
ENABLE_CAF_METADATA = False  # XCAF на крупных STEP может падать; включать выборочно
ENABLE_TRIMESH_VOID_HINT = False  # требует scipy; включить после pip install scipy
ENABLE_FACE_EDGE_TABLES = True

# Порог «мелкой» грани (мм²) для подсчёта мелких элементов
SMALL_FACE_AREA_MM2 = 25.0

# Тонкостенность: ray-casting OCC (IntCurvesFace + BRepClass3d)
ENABLE_WALL_THICKNESS_OCC = True
THIN_WALL_MIN_MM = 2.0
THIN_WALL_REL = 0.025
THIN_WALL_SAMPLE_RATIO = 0.15
WALL_THICKNESS_MAX_FACES = 55
WALL_THICKNESS_SAMPLES_PER_FACE = 2
# Отчёт: p10 вместо абсолютного min (сетки/перфорация дают ложные пики)
WALL_THICKNESS_REPORT_PERCENTILE = 10
WALL_THICKNESS_THIN_MEDIAN_FACTOR = 0.85

# Литьё (fast + force_wall_thickness): лимит времени ray-casting
CASTING_WALL_TIME_BUDGET_SEC = float(os.environ.get("SINLEX_CASTING_WALL_BUDGET_SEC", "45"))
CASTING_WALL_MAX_FACES = int(os.environ.get("SINLEX_CASTING_WALL_MAX_FACES", "55"))
CASTING_WALL_SAMPLES_PER_FACE = 2

# Fast-анализ: вероятностный гейт запуска ray-casting стенок (0..1, см. _wall_thickness_run_probability)
WALL_THICKNESS_RUN_THRESHOLD = float(os.environ.get("SINLEX_WALL_RUN_THRESHOLD", "0.45"))
WALL_THICKNESS_SA_V_MID = 0.22
WALL_THICKNESS_SA_V_SLOPE = 8.0
WALL_THICKNESS_DETAIL_MID = 14.0
WALL_THICKNESS_DETAIL_SLOPE = 0.15
# Вал/пруток: при sa/v ниже порога ray-casting не нужен
WALL_THICKNESS_SHAFT_SA_V_MAX = 0.25

# Отверстия на плитах: только bore-цилиндры с достаточной дугой (не радиусы рёбер)
MIN_HOLE_DIAMETER_MM = 5.5
MIN_HOLE_CIRC_SPAN_RAD = 4.0
HOLE_AXIS_CLUSTER_MM = 8.0

# Токарка / тело вращения (TZ-turning-rotation-classification)
BAR_STOCK_MAX_D_MM = 300.0
# Диск с фасонным контуром: если max outer-цилиндр < ratio×Ø bbox — Ø по огибающей
DISC_MIN_OUTER_CYL_TO_BBOX_RATIO = 0.75
ROD_MIN_LD_RATIO = 1.8
ROT_CONF_MIN_TURN = 0.60
ROT_CONF_BAR = 0.75
ROT_CONF_FORGING = 0.90
ROT_CONF_DISC = 0.80
ROT_CONF_HYBRID = 0.55
OUTER_AREA_SHARE_FORGING_MIN = 0.25
OUTER_DIAMETER_SPAN_MAX = 0.35
PLANE_PENALTY_FORGING_MAX = 0.55
AMBIGUOUS_OUTER_D_RATIO = 0.55
AMBIGUOUS_BORE_D_RATIO = 0.92
COAXIAL_ANGLE_DEG = 8.0
