#!/usr/bin/env bash
# Опциональные зависимости OCR для drawing_analysis (этап 2 TZ).
# GPU не обязателен; на CPU Paddle/EasyOCR заметно медленнее (до ~2 мин на 5 листов).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${SINLEX_PYTHON:-$ROOT/.conda/envs/sinlex/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python not found: $PYTHON" >&2
  echo "Set SINLEX_PYTHON to your env python." >&2
  exit 1
fi

echo "Installing optional drawing OCR packages into: $PYTHON"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install "paddlepaddle>=2.6" "paddleocr>=2.7" "easyocr>=1.7"

echo "Done. Enable with:"
echo "  export SINLEX_DRAWING_ENABLE_PADDLE=1"
echo "  export SINLEX_DRAWING_OCR_ENGINE=paddle   # or easyocr"
echo "Restart: systemctl restart sinlex-server sinlex-streamlit"
