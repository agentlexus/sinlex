"""Лимиты загрузки STEP/GLB и таймауты обработки (см. docs/TZ-step-upload-limits.md)."""

from __future__ import annotations

import os

MAX_STEP_UPLOAD_MB = 6
MAX_STEP_UPLOAD_BYTES = MAX_STEP_UPLOAD_MB * 1024 * 1024

# Таймауты HTTP к API (секунды; переопределение через env на VPS)
STEP_GLB_TIMEOUT_SEC = int(os.environ.get("SINLEX_STEP_GLB_TIMEOUT", "300"))
STEP_ANALYZE_TIMEOUT_SEC = int(os.environ.get("SINLEX_STEP_ANALYZE_TIMEOUT", "600"))
STEP_CASTING_ANALYZE_TIMEOUT_SEC = int(os.environ.get("SINLEX_CASTING_ANALYZE_TIMEOUT", "120"))
# Обратная совместимость
STEP_API_TIMEOUT_SEC = STEP_ANALYZE_TIMEOUT_SEC
GLB_FETCH_TIMEOUT_SEC = 30

# Файлы ≥ этого размера — fast-анализ OCC (без ray-casting стенок)
STEP_FAST_ANALYZE_MIN_BYTES = int(os.environ.get("SINLEX_STEP_FAST_MIN_BYTES", str(512 * 1024)))

# Inline GLB в 3D-viewer (data URI)
GLB_INLINE_MAX_MB = 20
GLB_INLINE_MAX_BYTES = GLB_INLINE_MAX_MB * 1024 * 1024

# Показывать расширенный спиннер при файлах ≥ 1 МБ
STEP_SPINNER_MIN_BYTES = 1 * 1024 * 1024


class StepProcessingError(RuntimeError):
    """Ошибка загрузки или обработки STEP."""


class StepProcessingTimeout(StepProcessingError):
    """Превышен таймаут API при обработке STEP."""


def format_step_max_size_label() -> str:
    return f"Максимальный размер файла: {MAX_STEP_UPLOAD_MB} МБ."


def validate_step_upload(file_bytes: bytes | None) -> str | None:
    """None если OK, иначе текст ошибки для UI."""
    if not file_bytes:
        return None
    n = len(file_bytes)
    if n > MAX_STEP_UPLOAD_BYTES:
        mb = n / (1024 * 1024)
        return (
            f"Файл слишком большой ({mb:.1f} МБ). "
            f"Допустимо не более {MAX_STEP_UPLOAD_MB} МБ для STEP."
        )
    return None


def is_large_step_upload(file_bytes: bytes | None) -> bool:
    return bool(file_bytes) and len(file_bytes) >= STEP_SPINNER_MIN_BYTES
