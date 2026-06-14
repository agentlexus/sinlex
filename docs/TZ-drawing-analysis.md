# ТЗ: улучшение анализа чертежа (PDF) + сверка с STEP

Версия: 2026-05-21  
Статус: планирование  
Аудитория: разработка Sinlex (форки чата по этапам)

---

## 0. Контекст (как сейчас)

| Компонент | Файл | Роль |
|-----------|------|------|
| UI загрузки PDF | `page_modules/pdf_analysis.py` | `scan-risk` → `expert-analysis`, техкарта |
| Проверка грифов | `risk_scanner.py` | `pdftotext` + regex, без ИИ |
| Экспертный анализ | `expert_analyzer.py` | `pdftotext` → fallback **Tesseract** (стр. 1, 150 DPI) → парсер полей → **DeepSeek** + STEP |
| API | `api/routers/analysis.py` | `/scan-risk`, `/expert-analysis`, `/tech-card` |
| Геометрия | `extraction_tool/extractor.py` | OCC, `build_expert_geometry_brief()` |
| Кэш анализа | `{project}/analysis_cache/{pdf_hash}_{step_version}.json` | |

**Принцип на весь проект:** STEP/OCC — источник истины по геометрии; чертёж — контроль и текст (материал, Ra, примечания). LLM не считает Ø и отверстия «с нуля», только интерпретирует готовый diff.

---

## 1. Целевая архитектура

```
PDF (N страниц)
  → drawing_reader (каскад извлечения текста)
  → drawing_parser (структура: штамп, размеры-текстом, Ra, примечания)
  → drawing_step_compare (детерминированная сверка с STEP)
  → expert_analyzer.deep_analysis (промпт + diff)
  → UI: блок «Чертёж vs модель»
```

Новый пакет (рекомендуется):

```
sinlex/drawing_analysis/
  __init__.py
  config.py          # лимиты страниц, DPI, флаги OCR
  reader.py          # pdftotext / tesseract / paddle (этапы 0–2)
  parser.py          # regex + поля (этап 1)
  compare.py         # сверка с STEP (этап 1)
  layout.py          # опционально PP-Structure (этап 3)
  vision.py          # опционально vision-LLM (этап 4)
```

`expert_analyzer.py` остаётся тонким: вызывает `drawing_analysis`, не дублирует логику.

---

## 2. Схемы данных (контракт между этапами)

### 2.1 `DrawingExtractionResult` (JSON, в кэш и в `step_data`)

```json
{
  "version": 1,
  "pdf_hash": "sha256...",
  "page_count": 3,
  "pages_processed": 3,
  "extraction_method": "pdftotext|tesseract|paddle|mixed",
  "per_page": [
    {
      "page": 1,
      "method": "pdftotext",
      "char_count": 1200,
      "text_preview": "..."
    }
  ],
  "full_text": "...(обрезка до 50k символов)...",
  "fields": {
    "designation": "",
    "name": "",
    "material": "",
    "mass": "",
    "dimensions_text": "",
    "tolerances": "",
    "roughness": [],
    "requirements": [],
    "notes": ""
  },
  "parsed_dimensions": [
    {"raw": "Ø6.4", "kind": "diameter", "value_mm": 6.4, "count_hint": 2, "page": 1}
  ],
  "warnings": []
}
```

### 2.2 `DrawingStepCompareResult`

```json
{
  "version": 1,
  "status": "ok|warning|error",
  "items": [
    {
      "code": "hole_count_mismatch",
      "severity": "warning",
      "drawing": "2×Ø6.4",
      "step": "2×Ø6.5",
      "message": "На чертеже 2 отверстия Ø6.4, в STEP — 2×Ø6.5"
    }
  ],
  "summary_ru": "2 расхождения, 0 критичных"
}
```

### 2.3 Расширение `data.txt` / `geometry` (опционально, этап 1)

```json
"drawing_extraction": { ...DrawingExtractionResult... },
"drawing_compare": { ...DrawingStepCompareResult... }
```

### 2.4 Версионирование кэша экспертного анализа

Текущий ключ: `{pdf_hash}_{step_analysis_version}.json`  
Добавить суффикс: `{pdf_hash}_{step_analysis_version}_draw_v{DRAWING_PIPELINE_VERSION}.json`  
`DRAWING_PIPELINE_VERSION` в `drawing_analysis/config.py` (начать с `1`).

---

## 3. Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `SINLEX_DRAWING_MAX_PAGES` | `5` | Макс. страниц OCR/текста |
| `SINLEX_DRAWING_OCR_DPI` | `150` | DPI для растра |
| `SINLEX_DRAWING_OCR_ENGINE` | `tesseract` | `tesseract` \| `paddle` \| `easyocr` |
| `SINLEX_DRAWING_ENABLE_PADDLE` | `0` | Включить Paddle fallback |
| `SINLEX_DRAWING_MIN_TEXT_CHARS` | `40` | Порог «достаточно pdftotext» на документ |
| `SINLEX_DRAWING_PIPELINE_VERSION` | `4` | Версия пайплайна для кэша |
| `SINLEX_DRAWING_ENABLE_LAYOUT` | `1` | Зоны штампа (этап 3) |
| `SINLEX_DEBUG` | — | Превью зон в UI (этап 3) |

---

## 4. Этапы (форки чата)

Каждый этап — **отдельный PR/чат**. В начале сессии: прочитать этот файл, секцию этапа N, проверить чеклист предыдущего этапа.

---

### Этап 0 — Мультистраничное извлечение текста

**Цель:** уйти с «только страница 1»; не менять LLM-промпт существенно.

**Файлы:**
- создать `drawing_analysis/reader.py`, `drawing_analysis/config.py`
- изменить `expert_analyzer.py`: `_read_drawing_from_pdf` → вызов `drawing_analysis.reader.extract_text_from_pdf`
- удалить дублирование логики Tesseract из `expert_analyzer` (перенос в reader)

**Задачи:**
1. `extract_text_per_page(pdf_bytes) -> list[PageText]`  
   - страница: попытка `pdftotext` (если есть `pdftotext -f N -l N`, иначе общий текст + эвристика разбиения);  
   - fallback: `pdf2image` + Tesseract на страницу;  
   - лимит `SINLEX_DRAWING_MAX_PAGES`.
2. `merge_pages(pages) -> full_text` с маркерами `\n--- Лист {n} ---\n`.
3. Сохранять `per_page` + `page_count` в результат.
4. `_parse_drawing_text_to_fields` вызывать от **полного** текста (перенести в `drawing_analysis/parser.py` как обёртку или импорт из expert).

**Критерии приёмки:**
- [ ] PDF 3+ листа: в `full_text` есть маркеры листов 1..N (N ≤ max_pages).
- [ ] Кэш экспертного анализа инвалидируется при смене `DRAWING_PIPELINE_VERSION`.
- [ ] Юнит-тест: mock bytes или фикстура PDF в `tests/test_drawing_reader.py` (опционально один smoke).
- [ ] `scan-risk` без изменений (по-прежнему весь документ через pdftotext).

**Не делать в этапе 0:** Paddle, сверка с STEP, UI.

**Промпт для форка чата:**
> Реализуй Этап 0 из `docs/TZ-drawing-analysis.md`: пакет `drawing_analysis`, мультистраничный reader, подключи в `expert_analyzer.py`.

---

### Этап 1 — Парсер размеров из текста + сверка с STEP

**Цель:** детерминированный diff «чертёж vs модель» без vision.

**Файлы:**
- `drawing_analysis/parser.py` — расширить поля + `parse_dimensions_from_text(text) -> list`
- `drawing_analysis/compare.py` — `compare_drawing_to_step(drawing, step_data) -> DrawingStepCompareResult`
- `expert_analyzer.py` — добавить блоки в промпт: `drawing_compare.summary_ru` + JSON items (top 10)
- `page_modules/pdf_analysis.py` — после экспертного анализа показать `st.expander("Чертёж vs модель")` если есть items
- `project_store` / сохранение: опционально писать `drawing_compare` в лог проекта

**Парсер (regex, минимум):**
- `Ø`, `ø`, `O`, `ф`, `Ф` + число (6.4, 6,4);
- `2×Ø6.4`, `2-Ø6.4`, `2 отв. Ø6.4`;
- `Ra 3.2`, `Rz`, `шероховатость`;
- габариты `\d+\s*[xх×]\s*\d+` (мм);
- материал — оставить эвристики из `_parse_drawing_text_to_fields`.

**Сверка (правила v1):**

| code | Условие |
|------|---------|
| `hole_diameter_mismatch` | Ø из чертежа vs `holes[]` STEP (допуск ±0.3 мм) |
| `hole_count_mismatch` | count_hint vs len(holes) кластера |
| `material_unknown_step` | материал в чертеже, в STEP пусто |
| `blank_family_hint` | слова «плита/лист» в тексте vs `part_family=plate` |
| `no_holes_on_drawing` | в тексте нет Ø, в STEP holes > 0 |

**Критерии приёмки:**
- [ ] Педаль: при OCR «2×Ø6.4» и STEP `2×Ø6.5` — warning `hole_diameter_mismatch`.
- [ ] Промпт DeepSeek содержит секцию «СВЕРКА ЧЕРТЁЖ/STEP»; в инструкции: не спорить с diff по отверстиям.
- [ ] UI показывает список расхождений без падения, если compare пустой.
- [ ] Не ломается `deep_analysis` без PDF (только STEP).

**Не делать:** Paddle, vision, layout.

**Промпт для форка:**
> Этап 1 TZ-drawing-analysis: parser размеров, compare с STEP, UI expander, промпт expert.

---

### Этап 2 — Каскад OCR (PaddleOCR / EasyOCR fallback)

**Цель:** лучшее распознавание сканов; pdftotext остаётся первым.

**Файлы:**
- `drawing_analysis/reader.py` — стратегия `CascadeReader`
- `drawing_analysis/config.py` — флаги движков
- `requirements` / `environment.yml` или скрипт `scripts/install_drawing_ocr.sh` (опциональные deps)
- документировать в README: GPU не обязателен, CPU медленнее

**Логика:**
```
for each page:
  t = pdftotext_page()
  if len(t) < MIN_PAGE_CHARS:
    t = ocr_page(engine=configured)  # tesseract | paddle | easyocr
  pages.append(t)
```

**Критерии приёмки:**
- [ ] `SINLEX_DRAWING_ENABLE_PADDLE=0` — поведение как этап 0 (только tesseract fallback).
- [ ] При включении Paddle — smoke на 1 скан-PDF (ручной чеклист в ТЗ-комментарии).
- [ ] Таймаут на весь PDF: 120 с, иначе `warnings: ["ocr_timeout"]`.
- [ ] Логировать `extraction_method` per page.

**Не делать:** layout, vision LLM.

**Промпт для форка:**
> Этап 2: Paddle/EasyOCR fallback в drawing_analysis.reader, env, таймауты.

---

### Этап 3 — Layout (грубые зоны: штамп / основная надпись)

**Цель:** структурировать поля, не распознавать размерные линии.

**Файлы:**
- `drawing_analysis/layout.py`
- опционально: PaddleOCR `PP-Structure` или эвристика по координатам Tesseract `image_to_data`

**Зоны (v1):**
- `title_block` — нижняя правая 25%×20% листа A4 (нормализованные bbox 0..1);
- `notes` — верх/лево текстовые блоки;
- `dimension_area` — всё остальное с паттерном `\d+[.,]\d*` и `Ø`.

**Критерии приёмки:**
- [x] `fields.designation` чаще заполняется на тестовом PDF проекта (ручная проверка 3 чертежей).
- [x] Fallback: если layout failed → parser по full_text как в этапе 1.

**Промпт для форка:**
> Этап 3: layout зоны штампа, интеграция в parser.fields.

---

### Этап 4 — Vision-LLM (опционально, флаг)

**Цель:** извлечь размеры с растра, когда OCR слабый; результат только через compare.

**Файлы:**
- `drawing_analysis/vision.py`
- `expert_analyzer.py` — вызов если `SINLEX_DRAWING_VISION=1` и `char_count < threshold`

**Промпт vision (шаблон):**
- 1 изображение / лист, JPEG 1024px max;
- JSON-only ответ: `dimensions[], roughness[], views_count`;
- жёсткая инструкция: не выдумывать, `unknown` если не видно.

**Сверка:** все значения vision проходят `compare.py`; в UI помечать `source: vision`.

**Критерии приёмки:**
- [ ] По умолчанию выключено (`SINLEX_DRAWING_VISION=0`).
- [ ] При включении — не падает без API key.

**Промпт для форка:**
> Этап 4: vision.py, флаг, интеграция в compare с source.

---

### Этап 5 — CV размерных линий (backlog, не MVP)

Только после стабильных этапов 0–2. Отдельное ТЗ: OpenCV линии + привязка OCR bbox. **Не начинать в первых форках.**

---

## 5. Изменения API (сквозные)

### 5.1 Ответ `/expert-analysis` (расширение)

```json
{
  "status": "ok",
  "analysis": "...",
  "api_used": "deepseek",
  "drawing_extraction": { ... },
  "drawing_compare": { ... }
}
```

Обратная совместимость: UI игнорирует новые поля, если старый кэш.

### 5.2 `step_data` в Form (без изменений контракта)

Клиент по-прежнему шлёт JSON; сервер обогащает при сохранении лога (этап 1).

---

## 6. Изменения промптов LLM

### `deep_analysis` — добавить после блока OCR:

```
СВЕРКА ЧЕРТЁЖ / STEP (детерминировано, приоритет над догадками):
{summary_ru}
{items_json}

Правила:
- По отверстиям и количеству — следуй сверке, не удваивай и не выдумывай Ø.
- Материал: чертёж vs STEP — укажи расхождение, если есть.
- Не комментируй качество OCR.
```

### `tech_card_analysis` — без изменений на этапах 0–1 (уже есть costing_quote).

---

## 7. UI (`pdf_analysis.py`)

| Этап | UI |
|------|-----|
| 0 | caption: «Обработано листов: N» |
| 1 | `st.expander("Чертёж vs модель")` — таблица severity / message |
| 2 | caption: метод OCR |
| 3 | опционально: мини-превью зон (debug, `SINLEX_DEBUG=1`) |

---

## 8. Тесты и эталоны

| ID | Деталь | Путь (пример) | Ожидание |
|----|--------|---------------|----------|
| T1 | Педаль | `projects/.../ЭПЛВФ.306569...stp` + PDF | plate, 2 holes STEP, compare warnings |
| T2 | PDF только текст | векторный PDF | pdftotext, 0 OCR |
| T3 | Многостраничный | любой 3-листовой | 3 маркера листа |

Команда smoke (после этапа 0):

```bash
/opt/sinlex/.conda/envs/sinlex/bin/python -c "
from drawing_analysis.reader import extract_text_from_pdf
import pathlib
pdf = pathlib.Path('...').read_bytes()
print(extract_text_from_pdf(pdf))
"
```

---

## 9. Риски и ограничения VPS

- Paddle + 5 страниц @ 150 DPI: до 60–120 с на CPU — нужен таймаут и spinner в UI.
- RAM: Paddle ~1–2 GB — мониторить на DEV VPS.
- Не хранить растр в кэше (только текст и hash), GDPR/размер.

---

## 10. Чеклист готовности продукта (все этапы 0–2)

- [ ] Этап 0 в main, кэш versioned
- [ ] Этап 1 compare на T1 (педаль)
- [ ] Этап 2 fallback опционален, по умолчанию off
- [ ] Документация env в `docs/TZ-drawing-analysis.md` (этот файл)
- [ ] `systemctl restart sinlex-server sinlex-streamlit` после deps

---

## 11. Порядок форков (кратко)

| # | Чат / ветка | Секция ТЗ |
|---|-------------|-----------|
| 1 | `feature/drawing-stage-0` | Этап 0 |
| 2 | `feature/drawing-stage-1` | Этап 1 |
| 3 | `feature/drawing-stage-2` | Этап 2 |
| 4 | `feature/drawing-stage-3` | Этап 3 (опционально) |
| 5 | `feature/drawing-stage-4` | Этап 4 (опционально) |

**В начале каждого чата писать:**
```
Реализуй Этап N из /opt/sinlex/docs/TZ-drawing-analysis.md.
Не трогай этапы N+1. Критерии приёмки — из секции этапа.
```

---

## 12. Связь с существующим кодом (референс)

```
expert_analyzer._read_drawing_from_pdf          → заменить на drawing_analysis
expert_analyzer._parse_drawing_text_to_fields   → перенести в drawing_analysis.parser
expert_analyzer.deep_analysis                   → + drawing_compare в промпт и ответ
risk_scanner._extract_text_from_pdf_bytes       → переиспользовать из reader (import)
extraction_tool: holes, part_family, setup_count_* → вход compare.py
```

---

*Конец ТЗ. Обновлять `DRAWING_PIPELINE_VERSION` при любом изменении формата `DrawingExtractionResult` или правил compare.*
