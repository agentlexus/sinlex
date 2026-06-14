# OCR чертежей (этап 2)

Опциональные движки PaddleOCR и EasyOCR подключаются через `drawing_analysis.reader.CascadeReader`.

## Установка

```bash
/opt/sinlex/scripts/install_drawing_ocr.sh
```

Базовый стек (`pytesseract`, `pdf2image`) уже в `requirements.txt`.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `SINLEX_DRAWING_ENABLE_PADDLE` | `0` | `1` — разрешить `paddle` / `easyocr` по `OCR_ENGINE` |
| `SINLEX_DRAWING_OCR_ENGINE` | `tesseract` | `tesseract` \| `paddle` \| `easyocr` (при `ENABLE_PADDLE=1`) |
| `SINLEX_DRAWING_OCR_TIMEOUT` | `120` | Таймаут на весь PDF, сек |
| `SINLEX_DRAWING_MIN_PAGE_CHARS` | `40` | Порог символов на странице для запуска OCR |

При `SINLEX_DRAWING_ENABLE_PADDLE=0` fallback OCR всегда **Tesseract** (как этап 0).

## Производительность

- **GPU не обязателен**; на CPU распознавание 5 листов @ 150 DPI может занять 60–120 с.
- При превышении таймаута в результате появится `warnings: ["ocr_timeout"]`.
- Растр в кэш не сохраняется — только текст и hash PDF.

## Smoke (скан с Paddle)

```bash
export SINLEX_DRAWING_ENABLE_PADDLE=1
export SINLEX_DRAWING_OCR_ENGINE=paddle
/opt/sinlex/.conda/envs/sinlex/bin/python -c "
from drawing_analysis.reader import extract_text_from_pdf
import pathlib
pdf = pathlib.Path('path/to/scan.pdf').read_bytes()
r = extract_text_from_pdf(pdf)
print(r['extraction_method'], r.get('per_page'))
"
```
