# ТЗ: стеки LLM (классика / углублённый), маркеры Sinlex AI 1.0 / 1.2

Версия: 2026-05-24  
Статус: **LP-0…LP-6 завершены**  
Связанные документы:
- [`TZ-llm-provider-priority.md`](TZ-llm-provider-priority.md) — расширенная спецификация (часть про «Супер-серверный анализ» **устарела**)
- [`TZ-hybrid-deep-analysis.md`](TZ-hybrid-deep-analysis.md) — гибрид, `suffler_text`, Max
- [`TZ-drawing-analysis.md`](TZ-drawing-analysis.md) — OCR/STEP до LLM

---

## 1. Два стека LLM (актуально)

| Режим | Кнопка / условие | Порядок LLM | Perplexity |
|-------|------------------|-------------|------------|
| **Классический** | «Анализировать», техкарта | **DeepSeek** → `sonar` | резерв |
| **Углублённый** | `deep_analysis(..., suffler_text=…)` после Max | **Perplexity** → DeepSeek | **`sonar-reasoning-pro`** |

Кэш `analysis_cache`:

| Режим | Суффикс файла |
|-------|----------------|
| Классика | `draw_v{N}_ds_primary_v1` |
| Углублённый | `draw_v{N}_hybrid_sonar_rp_v1_hybrid_{suffler_hash}` |

**История модели углублённого (2026-05-24):** сначала был `sonar-deep-research` — API 200, но часто **пустой `content`** → fallback на DeepSeek. Заменено на **`sonar-reasoning-pro`**; суффикс кэша `hybrid_sonar_rp_v1` (старый `hybrid_sonar_dr_v1` / `hybrid_ds_primary_v1` не читать).

Общие правила:

1. Ошибка LLM: `LLM_UI_ERROR_MESSAGE` = «**Сервер анализа временно недоступен**».
2. Маркеры **Sinlex AI 1.0 / 1.2 видимы** в UI (см. §2).
3. В UI **не показывать** DeepSeek, Perplexity, sonar, названия API.
4. Блок `suffler_text` в промпте углублённого анализа **не менять**.

---

## 2. Маркеры и брендинг

Промежуточный бренд **«Супер-серверный анализ»** (LP-1) **отменён**.

| `api_used` (только логи) | Маркер | UI |
|--------------------------|--------|-----|
| `perplexity` | **⚫** | **Sinlex AI 1.2** |
| `deepseek` | **🔵** | **Sinlex AI 1.0** |

Префикс в `analysis`:

```
⚫ Sinlex AI 1.2

<текст>
```

```
🔵 Sinlex AI 1.0

<текст>
```

Код: `expert_analyzer.format_llm_analysis_prefix()`, `normalize_analysis_display()`, `strip_analysis_prefix_for_llm()`.

**Legacy:** префиксы `🔵/⚫ Супер-серверный анализ` — снимать при показе и перед LLM; **Sinlex 1.0/1.2 не снимать**.

**Важно:** 🔵/⚫ привязаны к **провайдеру ответа**, не к режиму. Углублённый при успехе Perplexity → ⚫ 1.2; при fallback → 🔵 1.0.

---

## 3. Этапы (LP)

| ID | Содержание | Статус |
|----|------------|--------|
| **LP-0** | `_call_llm_with_fallback`, маркеры, тесты | ✅ |
| **LP-1** | `deep_analysis` + кэш (`ds_primary_v1` / `hybrid_sonar_rp_v1`) | ✅ |
| **LP-2** | `tech_card_analysis` + strip входа, DS primary | ✅ |
| **LP-3** | UI: ошибки, маркеры, кнопки (`pdf_analysis.py`) | ✅ |
| **LP-4** | Гибрид smoke (Max + finalize + маркер), гонка pending | ✅ |
| **LP-5** | `manufacturing_brief` → `_call_llm_with_fallback` | ✅ |
| **LP-6** | README | ✅ |

---

## 4. Сделано в backend (`expert_analyzer.py`)

| Константа | Значение |
|-----------|----------|
| `LLM_STACK_CLASSIC` | `ds_primary_v1` |
| `LLM_STACK_HYBRID` | `hybrid_sonar_rp_v1` |
| `PPLX_MODEL_HYBRID` | `sonar-reasoning-pro` |
| `PPLX_MODEL_DEFAULT` | `sonar` |
| `LLM_UI_ERROR_MESSAGE` | Сервер анализа временно недоступен |

| Функция | Поведение |
|---------|-----------|
| `_call_llm_with_fallback(primary=…)` | `deepseek`: DS→PPLX; `perplexity`: PPLX→DS |
| `deep_analysis` | без suffler → `primary=deepseek`; с suffler → `perplexity` + `sonar-reasoning-pro`, `HYBRID_MAX_OUTPUT_TOKENS=8000`, timeout 300 с |
| `tech_card_analysis` | strip входа; `primary=deepseek` |
| `build_expert_cache_suffix(suffler_text)` | см. §1 |

Тесты (18 шт.):

```bash
cd /opt/sinlex && .conda/envs/sinlex/bin/python -m unittest tests.test_expert_analyzer_llm -v
```

**Не трогать в LP-3:** `expert_analyzer.py`, гибрид, Max (`max_suffler.py`) — только UI.

---

## 5. LP-2 — выполнено ✅

- `tech_card_analysis`: `strip_analysis_prefix_for_llm`, `_call_llm_with_fallback(primary="deepseek")`, `LLM_UI_ERROR_MESSAGE`, `format_llm_analysis_prefix`.
- Тесты: `TestTechCardLp2` в `tests/test_expert_analyzer_llm.py`.

---

## 5.1 LP-5 — выполнено ✅

- `manufacturing_brief`: `_call_llm_with_fallback(primary="deepseek")`, `LLM_UI_ERROR_MESSAGE`, кэш `manufacturing_brief_{digest}_{LLM_STACK_CLASSIC}.json`, `strip_analysis_prefix_for_llm` для summary.
- Тесты: `TestManufacturingBriefLp5` в `tests/test_expert_analyzer_llm.py`.

---

## 5.2 LP-6 — README ✅

- Корневой [`README.md`](../README.md): раздел **«LLM: два стека и маркеры Sinlex AI»** — классика / углублённый, таблица маркеров ⚫ 1.2 / 🔵 1.0, ошибки, кэш, секреты без имён провайдеров в UI.
- [`secrets.env.example`](../secrets.env.example): комментарий к ключам LLM согласован с двумя стеками.

---

## 6. LP-3 — UI (`page_modules/pdf_analysis.py`) → Жорик

### 6.1 Цель

Согласовать Streamlit с backend: единая ошибка LLM, **видимые** маркеры Sinlex 1.0/1.2, без имён провайдеров.

### 6.2 Задачи

| # | Место | Было | Стало |
|---|-------|------|-------|
| 1 | Ошибка классического анализа (`process_pdf_scan`) | `st.error(f"Экспертный анализ: {msg}")` | Если `msg == LLM_UI_ERROR_MESSAGE` (или `status=error` от API) → **`st.error(LLM_UI_ERROR_MESSAGE)`** без префикса «Экспертный анализ:» |
| 2 | Гибрид: LLM недоступен после finalize | разные тексты | **`st.error(LLM_UI_ERROR_MESSAGE)`** |
| 3 | Гибрид: timeout suffler | «Анализ временно недоступен…» | **Оставить** «Анализ временно недоступен, попробуйте позже» (таймаут Max ≠ отказ LLM) |
| 4 | Гибрид: `hybrid_status == "error"` | «Анализ временно недоступен…» | Различать: отказ LLM → `LLM_UI_ERROR_MESSAGE`; прочее → текущая формулировка или caption |
| 5 | Показ экспертного / гибридного текста | `strip_provider_markers` → уже не срезает Sinlex | Убедиться, что **⚫/🔵 и Sinlex AI 1.0/1.2 видны** в `st.info`; legacy «Супер-серверный» по-прежнему скрыт |
| 6 | Техкарта: кнопка | `🤖 Sinlex AI анализ техпроцесса` | Допустимо: **«🤖 Сформировать техпроцесс»** или **«🤖 Технологический анализ»** — **без** слов DeepSeek/Perplexity |
| 7 | `is_deep_analysis_error()` | старые префиксы | Добавить распознавание `LLM_UI_ERROR_MESSAGE` и legacy ошибок API |
| 8 | Импорт | — | `from expert_analyzer import LLM_UI_ERROR_MESSAGE` (или через helper) |

### 6.3 Не делать в LP-3

- Менять `expert_analyzer.py`, API, гибридный polling, `max_suffler`.
- Менять маркеры 🔵/⚫ и подписи 1.0 / 1.2.
- Чинить приём ответа Max (это **LP-4** / отдельная задача по гонке `pending`).

### 6.4 Приёмка LP-3

- «Анализировать» при mock/реальном отказе LLM → только «Сервер анализа временно недоступен».
- Успешный анализ → в блоке видно **⚫ Sinlex AI 1.2** или **🔵 Sinlex AI 1.0** в начале текста.
- Техкарта: кнопка без AI-бренда провайдера; результат с маркером.
- Регрессия: гибрид pending / spinner без изменений логики опроса.

### 6.5 После деплоя

```bash
systemctl restart sinlex-streamlit.service   # или sinlex-streamlit
# sinlex-server уже с LP-1/2 — при правках только UI достаточно Streamlit
```

---

## 7. LP-4+ (кратко)

| Этап | Суть |
|------|------|
| **LP-4** | Smoke: PDF → Max → ответ → finalize → ⚫ или 🔵; проверить `api_used` в кэше |
| **LP-5** | `manufacturing_brief` → `_call_llm_with_fallback(primary="deepseek")` |
| **LP-6** | README: два стека, маркеры, без имён провайдеров |

**LP-4 (исправлено):** гонка «опрос `/updates` до `send_drawing`» — в `max_suffler`: pending регистрируется до upload; `check_response` не вызывает `/updates`, пока `task_id` нет в `pending`.

---

## 8. Промпт для агента **Жорик** (LP-3)

> Реализуй **LP-3** из `docs/ТЗ-смена-приоритета-LLM.md`.  
> Файл: **`page_modules/pdf_analysis.py`** (при необходимости импорт `LLM_UI_ERROR_MESSAGE` из `expert_analyzer`).  
>  
> **Сделать:** единое `st.error("Сервер анализа временно недоступен")` при отказе LLM (классика, гибрид finalize, техкарта); маркеры **⚫ Sinlex AI 1.2** / **🔵 Sinlex AI 1.0** **оставить видимыми** в `st.info`; обновить кнопку техкарты.  
>  
> **Не менять:** `expert_analyzer.py`, `max_suffler.py`, `hybrid_analysis.py`, маркеры и версии 1.0/1.2.  
>  
> Таймаут гибрида Max — по-прежнему «Анализ временно недоступен, попробуйте позже».  
>  
> После правок: перезапуск Streamlit, ручной smoke «Анализировать» + просмотр префикса в тексте.

---

## 9. Секреты

`secrets.env.example`: `SINLEX_PPLX_API_KEY`, `SINLEX_DS_API_KEY`.

---

## 10. Откат

Revert коммита LP-3 (`pdf_analysis.py`); backend LP-0…2 не откатывать без необходимости. При смене модели углублённого — bump `LLM_STACK_HYBRID` в `expert_analyzer.py`.
