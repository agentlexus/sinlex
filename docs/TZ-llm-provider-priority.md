# ТЗ: приоритет Perplexity, резерв DeepSeek, брендинг «супер-серверный анализ»

Версия: 2026-05-22  
Статус: **LP-2 завершён** (см. [`ТЗ-смена-приоритета-LLM.md`](ТЗ-смена-приоритета-LLM.md))  
Связанные документы:
- [`TZ-hybrid-deep-analysis.md`](TZ-hybrid-deep-analysis.md) — гибрид, `suffler_text`, finalize
- [`TZ-drawing-analysis.md`](TZ-drawing-analysis.md) — OCR/STEP до LLM
- [`TZ-costing-drawing-criteria.md`](TZ-costing-drawing-criteria.md) — критерии после экспертного анализа

---

## 0. Контекст (текущее состояние)

| Функция | Файл | Сейчас (LLM) | UI |
|---------|------|--------------|-----|
| Экспертный анализ | `expert_analyzer.deep_analysis` | только DeepSeek (`deepseek-chat`) | маркер 🔵 скрывается (`strip_provider_markers`) |
| Технологическая карта | `expert_analyzer.tech_card_analysis` | только DeepSeek | маркер 🔵 скрывается |
| Краткое резюме изготовления | `expert_analyzer.manufacturing_brief` | Perplexity → DeepSeek (уже так) | отдельный API, не на странице PDF |
| Гибрид finalize | `hybrid_analysis.finalize_hybrid_job` → `deep_analysis(..., suffler_text=...)` | тот же DeepSeek | «Углублённый режим», без имён провайдеров |

Внутренние имена провайдеров в коде/логах: `api_used`: `"perplexity"` | `"deepseek"`.  
В тексте ответа сейчас префиксы: `🔵 Sinlex AI 1.0` (DeepSeek), `⚫ Sinlex AI 1.2` (Perplexity).

**Секреты (не коммитить значения):** `SINLEX_PPLX_API_KEY` / `PERPLEXITY_API_KEY`, `SINLEX_DS_API_KEY` в `secrets.env`.

---

## 1. Цель

1. **Поменять приоритет LLM:** основной вызов — **Perplexity** (`sonar`), при недоступности — **DeepSeek** (`deepseek-chat`).
2. **Единое сообщение об ошибке в UI:** «**Сервер анализа временно недоступен**» (без «попробуйте позже» в обязательной формулировке; допустима вторичная подсказка мелким caption).
3. **Маркеры 🔵 и ⚫ видимы** в блоках экспертного анализа, углублённого анализа и техкарты.
4. **В UI запрещены** слова и бренды: DeepSeek, Perplexity, sonar, pplx, названия API, «Sinlex AI 1.0/1.2» как отсылка к провайдеру. Пользователь видит бренд **«Супер-серверный анализ»**.
5. **Не сломать** передачу `suffler_text` в LLM при гибриде (блок «ДАННЫЕ УГЛУБЛЁННОГО РАСПОЗНАВАНИЯ» в промпте, приоритет над OCR).

---

## 2. Область изменений

### 2.1 В scope

| Компонент | Изменение |
|-----------|-----------|
| `expert_analyzer.py` | Общая обёртка `_call_llm_primary_fallback()`; `deep_analysis`, `tech_card_analysis`, выравнивание `manufacturing_brief` |
| `page_modules/pdf_analysis.py` | Показ маркеров; единый текст ошибки; кнопка техкарты без «Sinlex AI» как провайдера |
| `api/routers/analysis.py` | Проброс `message` / `ui_message` без утечки имён провайдеров |
| `hybrid_analysis.py` | Только косвенно: finalize по-прежнему вызывает `deep_analysis` с `suffler_text` — поведение LLM меняется внутри `deep_analysis` |
| Кэш `analysis_cache/*.json` | Инвалидация / новый суффикс версии (см. §5) |
| Тесты | `tests/test_expert_analyzer_llm.py` (новый) или расширение существующих |

### 2.2 Вне scope

- OCR, `scan-risk`, `drawing_analysis`, `max_suffler`, логика `manufacturing_criteria` (кроме текста, пришедшего из LLM).
- Смена моделей, URL API, лимитов токенов (если не требуется для sonar на длинных промптах — отдельная подзадача).
- Публичная документация для конечного пользователя (кроме этого ТЗ).

---

## 3. Поведение LLM (backend)

### 3.1 Общая функция вызова

Ввести в `expert_analyzer.py` единый контракт:

```python
def _call_llm_with_fallback(
    prompt: str,
    *,
    max_tokens_primary: int = 4000,
    max_tokens_fallback: int = 4000,
) -> tuple[str | None, str | None]:
    """
    Returns (text, api_used).
    api_used: "perplexity" | "deepseek" | None
    """
```

**Порядок:**

1. `_call_perplexity(prompt, max_tokens=...)` — модель `sonar`, URL `https://api.perplexity.ai/chat/completions`.
2. При `None` / HTTP ≠ 200 / пустой content → `_call_deepseek(...)`.

**Логирование (сервер, не UI):** `logger.info("llm api_used=%s", api_used)` — допустимо. В ответе API поле `api_used` сохраняется для отладки и кэша; **Streamlit не показывает** значение `api_used` пользователю.

### 3.2 Экспертный анализ — `deep_analysis`

- Заменить прямой `_call_deepseek(prompt)` на `_call_llm_with_fallback(prompt, max_tokens_primary=4000, max_tokens_fallback=4000)`.
- Промпт **не менять** по смыслу; блок `suffler_text` (приоритет 1) остаётся как в §3.4.
- При `text is None` после обоих провайдеров:

```json
{
  "status": "error",
  "message": "Сервер анализа временно недоступен",
  "api_used": null
}
```

- При успехе — префикс маркера по §4.2, затем текст анализа.

### 3.3 Технологическая карта — `tech_card_analysis`

- Аналогично §3.2: Perplexity → DeepSeek.
- Те же `status` / `message` при полном отказе.
- Входной `analysis_text` для промпта — **без** маркера (см. §4.4): перед отправкой в LLM снимать префикс «Супер-серверный анализ».

### 3.4 Гибрид и `suffler_text` (критично)

| Требование | Реализация |
|------------|------------|
| `finalize_hybrid_job` не меняет сигнатуру | по-прежнему `deep_analysis(..., suffler_text=..., hybrid_task_id=...)` |
| Блок suffler в промпте | без изменений текста правил (приоритет 1 над OCR) |
| Кэш гибрида | суффикс `_hybrid_{suffler_hash}` сохраняется; добавить суффикс версии LLM (§5) |
| UI гибрида | те же маркеры и бренд; caption «Углублённый режим» **без** имён провайдеров |

**Запрещено:** отдельная ветка «только DeepSeek для гибрида» — гибрид использует тот же `_call_llm_with_fallback`, что и классический экспертный анализ.

### 3.5 `manufacturing_brief`

Уже Perplexity → DeepSeek. Привести к общим правилам:

- те же маркеры в `summary` (если когда-либо показывается в UI);
- `message` при ошибке: «Сервер анализа временно недоступен»;
- использовать `_call_llm_with_fallback` вместо дублирования логики.

### 3.6 Лимиты Perplexity на длинных промптах

Промпт `deep_analysis` может превышать комфортный лимит `sonar` (сейчас в `_call_perplexity` default `max_tokens=400` только для brief).

| Действие | Значение |
|----------|----------|
| `deep_analysis` / `tech_card_analysis` | `max_tokens` для Perplexity **не ниже 4000** (как у DeepSeek) |
| Таймаут HTTP Perplexity для длинных запросов | **180 с** (как DeepSeek), не 90 с |

При стабильных 413/length errors — зафиксировать в логе и в follow-up ТЗ (укорочение промпта / другая модель), не откатывать приоритет.

---

## 4. UI и брендинг

### 4.1 Запрещённые строки в интерфейсе

- DeepSeek, deepseek, Perplexity, perplexity, sonar, pplx, OpenAI-совместимые URL в подсказках.
- «Sinlex AI 1.0», «Sinlex AI 1.2» как обозначение провайдера.
- Показ поля `api_used` пользователю.

### 4.2 Маркеры (видимые)

Заменить префиксы в теле `analysis`:

| `api_used` (внутренний) | Маркер | Текст после маркера (первая строка) |
|-------------------------|--------|-------------------------------------|
| `perplexity` (основной) | 🔵 | **Супер-серверный анализ** |
| `deepseek` (резерв) | ⚫ | **Супер-серверный анализ** |

Формат префикса в JSON/кэше (одна строка заголовка + пустая строка):

```
🔵 Супер-серверный анализ

<текст анализа>
```

```
⚫ Супер-серверный анализ

<текст анализа>
```

**Смысл для пользователя:** оба канала — «супер-сервер»; эмодзи показывает, что ответ пришёл с основного (🔵) или резервного (⚫) сервера, **без** названия вендора.

### 4.3 `pdf_analysis.py`

| Место | Было | Стало |
|-------|------|-------|
| `strip_provider_markers` | удаляет 🔵/⚫ префиксы | **переименовать** в `normalize_analysis_display` / оставить strip только для **устаревших** префиксов (`Sinlex AI 1.0`, `Sinlex AI 1.2`) при чтении старого кэша; **новые** префиксы «Супер-серверный анализ» **не снимать** |
| `st.info(...)` эксперт / гибрид | `strip_provider_markers(analysis)` | показывать текст **с** маркером |
| Ошибки LLM / hybrid timeout | «Анализ временно недоступен…» | **`st.error("Сервер анализа временно недоступен")`** |
| Кнопка техкарты | «🤖 Sinlex AI анализ техпроцесса» | **«🤖 Супер-серверный анализ техпроцесса»** (или «Сформировать техпроцесс» — выбрать один вариант при реализации, без AI-бренда провайдера) |
| `is_deep_analysis_error` | по подстрокам старых сообщений | добавить распознавание «Сервер анализа временно недоступен» |

### 4.4 Техкарта: вход в LLM

Перед `tech_card_analysis` на сервере (или в UI при POST) из `analysis_text` удалять:

- новые префиксы `🔵/⚫ Супер-серверный анализ\n\n`;
- legacy `🔵 Sinlex AI 1.0`, `⚫ Sinlex AI 1.2`.

Иначе модель дублирует заголовки.

### 4.5 Гибрид — сообщения

| Событие | UI |
|---------|-----|
| Ожидание Max | без изменений: «Выполняется углублённый анализ…» |
| LLM недоступен после finalize | «Сервер анализа временно недоступен» |
| Таймаут suffler (1 ч) | можно оставить «Анализ временно недоступен…» **или** унифицировать на «Сервер анализа временно недоступен» — **рекомендация:** timeout suffler = «Анализ временно недоступен…»; отказ LLM = «Сервер анализа временно недоступен» (разные причины) |

---

## 5. Кэш

### 5.1 Проблема

Записи в `analysis_cache/{pdf_hash}_{step_ver}_draw_v4[_hybrid_*].json` содержат старый `api_used` и префиксы. После смены приоритета возможен **устаревший текст** (сгенерированный только DeepSeek).

### 5.2 Решение

Ввести константу в `expert_analyzer.py`:

```python
LLM_STACK_VERSION = "pplx_primary_v1"  # bump при смене политики LLM
```

Суффикс файла кэша для экспертного анализа:

- было: `draw_v{DRAWING_PIPELINE_VERSION}`
- стало: `draw_v{DRAWING_PIPELINE_VERSION}_{LLM_STACK_VERSION}`

Гибрид: `draw_v{N}_{LLM_STACK_VERSION}_hybrid_{suffler_hash}`.

**Старые файлы без `LLM_STACK_VERSION` не читать** для новых запросов (промах кэша → новый вызов LLM).

### 5.3 Поле `api_used` в JSON

Сохранять для админ-логов. UI не интерпретирует.

---

## 6. API (контракт)

Эндпоинты **без смены URL**:

- `POST /expert-analysis`
- `POST /tech-card`
- `POST /hybrid-analysis/finalize/{task_id}`

Ответ при ошибке LLM:

```json
{
  "status": "error",
  "message": "Сервер анализа временно недоступен",
  "api_used": null
}
```

Успех — без изменения структуры; в `analysis` — текст **с** маркером §4.2.

---

## 7. Этапы реализации

| ID | Задача | Файлы | Критерий готовности |
|----|--------|-------|---------------------|
| **LP-0** | `_call_llm_with_fallback`, маркеры, `LLM_STACK_VERSION` | `expert_analyzer.py` | [x] unit-тест: mock PPLX fail → DS ok; mock оба fail → error message |
| **LP-1** | `deep_analysis` + кэш-суффикс | `expert_analyzer.py` | [x] unit-тест; smoke: 🔵/⚫ + «Супер-серверный анализ» |
| **LP-2** | `tech_card_analysis` + strip входа | `expert_analyzer.py` | [x] unit-тест; smoke: маркер в ответе |
| **LP-3** | UI: маркеры, ошибки, кнопка | `pdf_analysis.py` | нет strip новых маркеров; единая ошибка LLM |
| **LP-4** | Гибрид smoke | `hybrid_analysis` + UI | suffler_text в промпте (лог/assert); результат с маркером |
| **LP-5** | `manufacturing_brief` выравнивание | `expert_analyzer.py` | общая обёртка, те же сообщения |
| **LP-6** | Документация README | `README.md` | убрать публичные «DeepSeek/Perplexity» в user-facing описании LLM; оставить env vars для админов |

---

## 8. Тесты и приёмка

### 8.1 Автотесты

- `deep_analysis`: при успешном Perplexity → `api_used=="perplexity"`, префикс `🔵 Супер-серверный анализ`.
- `deep_analysis`: Perplexity `None`, DeepSeek ok → `api_used=="deepseek"`, префикс `⚫`.
- `deep_analysis`: оба `None` → `status=="error"`, `message` содержит «Сервер анализа временно недоступен».
- `deep_analysis(..., suffler_text="Маховик")`: в mock-промпте есть подстрока `ДАННЫЕ УГЛУБЛЁННОГО РАСПОЗНАВАНИЯ` и `Маховик`.
- `tech_card_analysis`: вход с маркером → в промпт уходит текст без префикса.
- Legacy cache read: файл со старым префиксом `Sinlex AI 1.0` отображается в UI (миграция strip legacy only).

### 8.2 Ручной smoke

1. «Анализировать» на safe PDF → текст с видимым 🔵 или ⚫ и «Супер-серверный анализ».
2. «Углублённый анализ» → ответ Max → finalize → тот же формат маркера; критерии/стоимость пересчитаны.
3. Техкарта после эксперта → маркер виден, нет слов DeepSeek/Perplexity на экране.
4. Отключить `SINLEX_PPLX_API_KEY` (только DS) → ответ с ⚫, UI работает.
5. Отключить оба ключа → «Сервер анализа временно недоступен».

### 8.3 Регрессия (не ломать)

- Кнопка «Анализировать» и `/expert-analysis` — те же поля `drawing_extraction`, `drawing_compare`, `drawing_manufacturing_criteria`.
- `scan-risk` без LLM.
- Классический и гибридный потоки независимы по session keys (`hybrid_*` vs `deep_analysis_*`).

---

## 9. Откат

1. `LLM_STACK_VERSION` → предыдущее значение или удалить суффикс из кэша.
2. Вернуть прямой вызов DeepSeek в `deep_analysis` / `tech_card_analysis` (один коммит revert).
3. `ENABLE_HYBRID_SUFFLER` не трогать.

---

## 10. Сводка для исполнителя

> Perplexity первый, DeepSeek запасной — для **экспертного анализа** и **техкарты**.  
> В UI: видимые 🔵/⚫ + «Супер-серверный анализ», ошибка LLM — «Сервер анализа временно недоступен», без имён провайдеров.  
> `suffler_text` и блок приоритета 1 в промпте **не трогать**.  
> Кэш — новый суффикс `LLM_STACK_VERSION`, старые записи не подмешивать.
