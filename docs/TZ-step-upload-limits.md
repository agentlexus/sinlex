# TZ: лимиты загрузки STEP и обработка на странице Upload

Версия: 2026-05-22  
Статус: реализовано (этапы 1–4)

---

## 1. Цель

Стабильная загрузка и обработка STEP до **6 МБ**: понятный лимит в UI, увеличенные таймауты, сброс «зависшей» сессии, индикатор ожидания, превью GLB до **20 МБ** inline.

---

## 2. Лимиты (константы)

| Параметр | Значение | Файл |
|----------|----------|------|
| Макс. STEP в uploader | **6 МБ** | `page_modules/upload_limits.py` → `MAX_STEP_UPLOAD_MB` |
| Таймаут GLB (`/step-to-glb`) | **300 с** | `STEP_GLB_TIMEOUT_SEC` |
| Таймаут анализа (`/analyze-step`) | **600 с** | `STEP_ANALYZE_TIMEOUT_SEC` |
| Fast-анализ OCC | файл **≥ 512 КБ** | без ray-casting стенок, упрощённый обход граней |
| Inline GLB в 3D-viewer | **20 МБ** | `GLB_INLINE_MAX_MB` |
| Спиннер «тяжёлый файл» | ≥ **1 МБ** | `STEP_SPINNER_MIN_BYTES` |
| nginx `/api/` read/send timeout | **660 с** | `/etc/nginx/sites-available/sinlex` |
| Streamlit `maxUploadSize` (глобально) | 200 МБ | `config.toml` (PDF и пр.) |
| Streamlit `maxMessageSize` | 220 МБ | `config.toml` (запас под GLB в session) |

STEP: в `st.file_uploader` — `max_upload_size=6` и подсказка «Максимальный размер файла: 6 МБ».

PDF: без изменения (до 200 МБ через глобальный `maxUploadSize`).

---

## 3. Этапы

### Этап 1 — UI: подпись 6 МБ и проверка размера

**Файлы:** `5_Upload.py`, `upload_limits.py`

**Задачи:**

1. Убрать восприятие «200 МБ» для STEP: `help` + `max_upload_size=6`.
2. `validate_step_upload()` после чтения файла и перед обработкой.

**Критерии приёмки:**

- [x] В подсказке uploader указано «максимум 6 МБ».
- [x] Файл > 6 МБ отклоняется с сообщением, без вызова API.

---

### Этап 2 — Таймауты API и nginx

**Файлы:** `upload_step.py`, nginx `sinlex`

**Задачи:**

1. `/step-to-glb`: **300 с**; `/analyze-step`: **600 с** (отдельные таймауты).
2. nginx `location /api/`: **660 с**.
3. Fast-режим OCC для файлов ≥ 512 КБ (`extract_step_bytes(fast=True)`).

**Критерии приёмки:**

- [x] STEP 4–6 МБ на тяжёлой геометрии не обрывается на 180 с; анализ до 10 мин.

---

### Этап 3 — Сброс сессии при таймауте

**Файлы:** `upload_step.py`, `5_Upload.py`

**Задачи:**

1. `reset_step_processing_session(clear_upload=True)` — GLB-кэш, анализ STEP, флаг `_step_load_in_progress`, при таймауте — `cached_step`.
2. `StepProcessingTimeout` при `requests.Timeout` на конвертации и analyze-step.
3. В `5_Upload.py` при таймауте/ошибке — сброс + `st.stop()`.

**Критерии приёмки:**

- [x] После таймаута страница не зацикливается на «висящей» обработке.
- [x] Пользователь видит сообщение и может загрузить файл снова.

---

### Этап 4 — Спиннер и GLB 20 МБ

**Файлы:** `5_Upload.py`, `viewer_3d.py`

**Задачи:**

1. `st.spinner` при обработке STEP (для ≥ 1 МБ — с размером в тексте).
2. `GLB_INLINE_MAX_BYTES` = 20 МБ (было 12).

**Критерии приёмки:**

- [x] При загрузке/конвертации виден бегунок.
- [x] GLB до 20 МБ встраивается в viewer через data URI; больше — загрузка по URL API.

---

## 4. Зависимости

| Этап | Зависит от |
|------|------------|
| 2 | 1 |
| 3 | 2 |
| 4 | 1 |

Порядок: **1 → 2 → 3 → 4**.

---

## 5. Деплой

```bash
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl restart sinlex-streamlit sinlex-server
```

---

## 6. Промпт для форка

> Реализуй этап N из `/opt/sinlex/docs/TZ-step-upload-limits.md`. Не трогай этапы N+1.
