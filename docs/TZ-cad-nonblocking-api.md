# TZ: неблокирующая обработка STEP/CAD в API

Версия: 2026-06-24  
Статус: к реализации (локально → push → prod)

Связано: [`docs/TZ-step-upload-limits.md`](TZ-step-upload-limits.md)

---

## 1. Проблема

На prod (`sinlex-server`, один процесс uvicorn на `:8001`) тяжёлые **синхронные** операции OpenCASCADE/trimesh выполняются **внутри async-эндпоинтов** и блокируют event loop.

**Симптомы (2026-06-24):**
- `sinlex-server` ~80% CPU, API не отвечает (timeout 5+ с на `/docs`, `/payments/*`, hybrid status).
- Последний лог перед зависанием: `extractor.py` / `step_convert.py` (`brepbndlib_Add`, `brepgprop_VolumeProperties`).
- Триггеры: `POST /analyze-step`, `POST /step-to-glb`, иногда цепочка upload → GLB → analyze (`BODY_2944`, `PANL_2881_00_A`).
- Предыдущий экземпляр uvicorn накопил **~2 ч CPU** до перезапуска.

**Корень:** один worker, CPU-bound код без `run_in_executor` — пока один пользователь грузит STEP, **весь sinlex.tech** тормозит (другие проекты, «Поток», баланс, 3D-viewer).

---

## 2. Цель

1. **API остаётся отзывчивым** во время analyze-step / step-to-glb (другие запросы < 1 с).
2. Поведение для Upload **не меняется** с точки зрения UI: те же эндпоинты, те же таймауты, тот же JSON.
3. Не более **одной** тяжёлой CAD-задачи одновременно на инстанс (очередь или semaphore), чтобы не убить RAM/CPU двумя OCC.

**Не в scope v1:** async job + polling (`task_id` для analyze), отдельный worker-процесс, несколько uvicorn workers.

---

## 3. Затронутые эндпоинты

| Эндпоинт | Файл | Блокирующий вызов |
|----------|------|-------------------|
| `POST /analyze-step` | `api/routers/cad.py` | `step_analyzer.analyze_step()` → `extract_step_bytes` |
| `POST /step-to-glb` | `api/routers/cad.py` | `step_bytes_to_glb_response()` → OCC + trimesh export |
| `GET /projects/glb/{name}` | `api/routers/projects.py` | `ensure_glb_from_stp()` → `convert_step_file_to_glb()` (если GLB ещё нет) |

**Опционально v2** (тоже sync, но реже блокируют надолго):
- `POST /expert-analysis` → `deep_analysis()` (`api/routers/analysis.py`)
- `POST /hybrid-analysis/finalize/{task_id}` → LLM (`hybrid_analysis.finalize_hybrid_job`)

---

## 4. Решение (v1 — рекомендуется)

### 4.1. Общий executor для CAD

Новый модуль: **`api/services/cad_executor.py`**

```python
# Концепт
import asyncio
from concurrent.futures import ThreadPoolExecutor

_CAD_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sinlex-cad")
_CAD_SEM = asyncio.Semaphore(1)  # не более 1 тяжёлой задачи

async def run_cad(fn, *args, timeout: float | None = None):
    async with _CAD_SEM:
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(_CAD_POOL, fn, *args)
        if timeout:
            return await asyncio.wait_for(fut, timeout=timeout)
        return await fut
```

- **`max_workers=1`** — один поток OCC (GIL + память); параллель два STEP на 4 GB VPS недопустимы.
- **`Semaphore(1)`** — если analyze уже идёт, второй запрос **ждёт в очереди**, но event loop **свободен** для лёгких GET.
- Таймауты: analyze **600 с**, glb **300 с** (как в `upload_limits.py` / env `SINLEX_STEP_*`).

### 4.2. Изменения в `api/routers/cad.py`

**`analyze-step`:**
```python
content = await file.read()
result = await run_cad(
    lambda: analyze_step(content, force_wall_thickness=casting),
    timeout=STEP_ANALYZE_TIMEOUT_SEC,
)
# post-process main_dim как сейчас
```

**`step-to-glb`:**
- Чтение файла — в async (как сейчас).
- `step_bytes_to_glb_response(step_path, glb_path)` — через `run_cad(..., timeout=STEP_GLB_TIMEOUT_SEC)`.

При `asyncio.TimeoutError` → HTTP **504** с текстом «Превышено время обработки STEP».

### 4.3. `ensure_glb_from_stp` / `GET /projects/glb`

`ensure_project_glb()` вызывается из **async** роутера, но внутри синхронный `convert_step_file_to_glb`.

Вариант A (минимальный): обернуть только медленную ветку «GLB не существует»:

```python
# api/services/projects_fs.py или в роутере
if not os.path.exists(glb_path):
    await run_cad(lambda: convert_step_file_to_glb(stp_path, glb_path), timeout=STEP_GLB_TIMEOUT_SEC)
```

Если GLB уже на диске — мгновенный `FileResponse` без executor.

### 4.4. Константы

Вынести таймауты server-side в **`page_modules/upload_limits.py`** или дублировать в `cad_executor.py` с теми же env:

| Env | Default | Назначение |
|-----|---------|------------|
| `SINLEX_STEP_ANALYZE_TIMEOUT` | 600 | analyze-step |
| `SINLEX_STEP_GLB_TIMEOUT` | 300 | step-to-glb, ensure_glb |
| `SINLEX_CAD_MAX_WORKERS` | 1 | потоки executor (не увеличивать на prod без RAM) |

Клиентские таймауты в `upload_step.py` уже ≥ server-side — менять не обязательно.

---

## 5. Что НЕ делать

| Подход | Почему нет |
|--------|------------|
| `--workers 4` uvicorn | 4× память OCC, GIL, риск OOM на 4 GB VPS |
| Отдельный microservice | overkill для v1 |
| Background job + poll для analyze | ломает контракт Upload (ждёт sync POST) — только v2 |
| Убивать процесс по timeout | грубо; достаточно 504 + semaphore |

---

## 6. Задачи (чеклист для локала)

| ID | Область | Задача |
|----|--------|--------|
| **CAD-1** | `api/services/cad_executor.py` | Executor + semaphore + `run_cad()` + таймауты |
| **CAD-2** | `api/routers/cad.py` | `analyze-step` и `step-to-glb` через `run_cad` |
| **CAD-3** | `api/services/projects_fs.py` или `projects.py` | `ensure_project_glb` — async-обёртка генерации GLB |
| **CAD-4** | `tests/test_cad_executor.py` | Mock: пока CAD «спит» 2 с, параллельный GET `/health` или `/projects` отвечает < 500 ms |
| **CAD-5** | `tests/test_cad_router.py` | Mock `analyze_step`: 504 при timeout |
| **CAD-6** | `secrets.env.example` | Комментарий к `SINLEX_STEP_*` / `SINLEX_CAD_MAX_WORKERS` |
| **CAD-7** | README или cross-link | Ссылка из `TZ-step-upload-limits.md` |

---

## 7. Тесты

### 7.1. Unit — executor

```python
# tests/test_cad_executor.py
async def test_light_request_not_blocked_by_cad():
    # run_cad(time.sleep, 3) в фоне (create_task)
    # параллельно await run_cad(lambda: "ok", ...) или mock health — второй вызов не deadlocks
```

### 7.2. Integration (опционально, без OCC)

Patch `analyze_step` → `time.sleep(5)`; `httpx.AsyncClient` + `TestClient`:
- запрос A: `POST /analyze-step` (фон)
- запрос B: `GET /projects` — **200 за < 1 с**

### 7.3. Smoke на prod (после деплоя)

1. Открыть тяжёлый STEP на Upload (ожидание analyze).
2. В другой вкладке / у другого пользователя — открыть LID_1702, проверить hybrid status / flow-balance **< 2 с**.
3. `curl -w '%{time_total}' http://127.0.0.1:8001/docs` во время analyze — **< 1 с**.

---

## 8. Критерии приёмки

- [ ] Во время `POST /analyze-step` (файл ≥ 1 МБ, OCC ≥ 30 с) эндпоинты `GET /projects`, `/payments/flow-balance`, `/hybrid-analysis/status/*` отвечают без timeout.
- [ ] `POST /step-to-glb` не блокирует event loop (тот же тест).
- [ ] При превышении server timeout — **504**, UI показывает сообщение (существующий `StepProcessingTimeout` на клиенте).
- [ ] Не более одной CAD-операции одновременно (второй analyze ждёт, не падает).
- [ ] Unit-тесты CAD-4, CAD-5 зелёные.
- [ ] Регрессия: `tests/test_upload_limits.py`, `tests/test_email_logistics.py` — без изменений поведения.

---

## 9. Деплой

1. Push в `main` → GitHub Actions.
2. `systemctl restart sinlex-server` (достаточно; streamlit не меняется).
3. Smoke (раздел 7.3).

Rollback: revert commit + restart `sinlex-server`.

---

## 10. v2 (не обязательно сейчас)

- `deep_analysis` / `finalize_hybrid_job` в тот же executor или отдельный LLM-pool.
- Метрика Prometheus/log: `cad_job_duration_sec`, `cad_queue_wait_sec`.
- Admin-эндпоинт `GET /internal/cad-status` (queued/running) для диагностики без `kill -9`.

---

## 11. Ссылки на код

| Компонент | Путь |
|-----------|------|
| Блокирующие роуты | `api/routers/cad.py` |
| Анализ STEP | `step_analyzer.py` → `extraction_tool/extractor.py` |
| GLB | `api/services/step_convert.py` |
| Upload UI | `page_modules/upload_step.py` |
| Таймауты клиента | `page_modules/upload_limits.py` |
| systemd | `deploy/systemd/sinlex-server.service` (workers не добавлять) |
