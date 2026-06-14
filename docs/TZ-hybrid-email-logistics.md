# ТЗ: канал углублённого анализа — переключение JSON + `email_logistics`

Версия: 2026-05-25  
Статус: **HE-0…HE-3 реализованы**; HE-4…HE-6 — smoke и доработки  
Связанные документы:
- [`TZ-hybrid-deep-analysis.md`](TZ-hybrid-deep-analysis.md) — гибрид, job, UI, API (HS-0…HS-8)
- [`ТЗ-смена-приоритета-LLM.md`](ТЗ-смена-приоритета-LLM.md) — стеки LLM после ответа канала
- [`README.md`](../README.md) — переменные окружения (обновить после HE-6)

---

## 1. Цель

1. **Отключить бота Max** как канал по умолчанию; оставить возможность включить через конфиг (legacy).
2. Ввести **email-транспорт** в модуле **`email_logistics`** — исходящие задачи и приём текстовых ответов на **один служебный ящик**.
3. Выбор активного канала — **переключатель в JSON-файле** (без правки кода и без пересборки).
4. Сохранить контракт гибрида: `hybrid_analysis` → отправка PDF → ожидание → `suffler_text` → `deep_analysis` → UI.

**Ограничение UX (без изменений):** в UI не упоминать email, SMTP, IMAP, Max, «суфлер», провайдеров LLM.

---

## 2. Контекст (что уже есть)

| Компонент | Роль |
|-----------|------|
| `hybrid_analysis.py` | Job `{project}/hybrid_jobs/{task_id}.json`, таймаут, finalize |
| `max_suffler.py` | Канал Max: `send_drawing`, `check_response`, state `data/hybrid_suffler_state.json` |
| `api/routers/hybrid_analysis.py` | start / status / finalize |
| `page_modules/pdf_analysis.py` | Кнопка, polling `SUFFLER_POLL_INTERVAL_SEC` |
| `expert_analyzer.deep_analysis` | `suffler_text`, LLM, кэш |

**Проблема Max в проде:** один `MAX_SUFFLER_CHAT_ID` на всех пользователей; параллельные задачи без reply рискуют перепутать ответ. Email с **обязательным reply по цепочке** и `Message-ID` снимает часть риска при одном ящике.

---

## 3. Переключатель каналов (JSON)

### 3.1 Файл конфигурации

Путь по умолчанию:

```
/opt/sinlex/config/hybrid_channel.json
```

Переопределение: переменная окружения или `secrets.env`:

```
HYBRID_CHANNEL_CONFIG=/opt/sinlex/config/hybrid_channel.json
```

Файл **можно коммитить** (без паролей). Секреты SMTP/IMAP — только в `secrets.env`.

### 3.2 Схема JSON (v1)

```json
{
  "version": 1,
  "active_channel": "email_logistics",
  "channels": {
    "email_logistics": {
      "enabled": true
    },
    "max_suffler": {
      "enabled": false
    }
  }
}
```

| Поле | Тип | Описание |
|------|-----|----------|
| `version` | `1` | Версия схемы; при неизвестной — ошибка конфигурации в лог, UI: углублённый режим недоступен |
| `active_channel` | `"email_logistics"` \| `"max_suffler"` | Единственный активный транспорт |
| `channels.*.enabled` | `bool` | Доп. предохранитель: `active_channel` должен иметь `enabled: true` |

**Правила:**

1. При `ENABLE_HYBRID_SUFFLER=0` в env кнопка «Углублённый анализ» **скрыта** (как сейчас), JSON не читается.
2. При `ENABLE_HYBRID_SUFFLER=1` читается JSON; если `active_channel` выключен или файл битый — `MaxSufflerError` / аналог с `code=config`, UI: «Углублённый анализ недоступен».
3. **Прод по умолчанию после внедрения:** `active_channel: "email_logistics"`, `max_suffler.enabled: false`.
4. Переключение Max → email: правка JSON + `systemctl restart sinlex-server` (перечитать конфиг при старте воркера; опционально — reload без рестарта в HE-5).

### 3.3 Пример `config/hybrid_channel.json` (шаблон в репозитории)

```json
{
  "version": 1,
  "active_channel": "email_logistics",
  "channels": {
    "email_logistics": {
      "enabled": true
    },
    "max_suffler": {
      "enabled": false
    }
  }
}
```

---

## 4. Модуль `email_logistics`

### 4.1 Расположение

```
/opt/sinlex/email_logistics/
  __init__.py          # экспорт EmailLogisticsChannel, get_hybrid_channel, ошибки
  channel.py           # класс канала
  smtp_send.py         # отправка
  imap_receive.py      # приём / сопоставление reply
  markers.py           # #sinlex-hybrid, парсинг task_id (общие константы с max_suffler или shared)
  config.py            # чтение hybrid_channel.json + env
```

**Не смешивать** с `max_suffler.py`: Max остаётся legacy-адаптером за флагом `max_suffler`.

### 4.2 Единый фасад канала

```python
# email_logistics/__init__.py (и использование в hybrid_analysis)

class HybridChannel(Protocol):
    def send_drawing(
        self,
        pdf_bytes: bytes,
        project_name: str,
        task_id: str,
        *,
        user_folder: str = "",
    ) -> str: ...

    def check_response(self, task_id: str) -> str | None: ...

    def parse_response(self, text: str) -> dict: ...


def get_hybrid_channel() -> HybridChannel:
    """Читает hybrid_channel.json → email_logistics | MaxSufflerBot."""
```

`hybrid_analysis.py` **переходит** с `get_max_suffler_bot()` на `get_hybrid_channel()`.  
Исключения: общий базовый класс `HybridChannelError` (коды `config`, `network`, `api`) и те же `ui_message`, что у `MaxSufflerError`.

### 4.3 Исходящее письмо (задача)

**Кому:** `SUFFLER_EMAIL_TO` (один адрес технологов / общий ящик).  
**От кого:** `SUFFLER_EMAIL_FROM` (службный ящик Sinlex).

| Часть | Содержание |
|-------|------------|
| Вложение | `drawing.pdf` (bytes из job) |
| Subject | `[Sinlex] Углублённый анализ — {project_name}` (без слов «бот», «Max») |
| Body (plain text) | Маркеры + поля для человека |

Тело (обязательный машиночитаемый блок):

```
#sinlex-hybrid
task_id:550e8400-e29b-41d4-a716-446655440000
user_folder:sinlex_admin
project:1.С.2.09994.17.00.00.02МД_Маховик

Чертёж во вложении. Ответьте в этой цепочке (Reply) текстом распознавания.
```

**После отправки** сохранить в state:

| Ключ | Значение |
|------|----------|
| `task_id` | UUID job |
| `message_id` | RFC `Message-ID` исходящего письма |
| `sent_at` | ISO8601 |
| `user_folder`, `project_name` | для логов |
| `pending` | до получения ответа |

Файл state по умолчанию: `/opt/sinlex/data/email_logistics_state.json`  
Переопределение: `EMAIL_LOGISTICS_STATE_FILE`.

### 4.4 Входящий ответ

Опрос **IMAP** (папка `SUFFLER_IMAP_FOLDER`, по умолчанию `INBOX`) при каждом `check_response(task_id)` для данного pending — аналог `_poll_updates` у Max.

**Сопоставление ответа с task (порядок приоритета):**

| # | Условие | Надёжность |
|---|---------|------------|
| 1 | Заголовки `In-Reply-To` / `References` содержат сохранённый `Message-ID` исходящего | **Высокая** (основной сценарий) |
| 2 | В теле (plain или html→text) есть `task_id:{uuid}` или `#sinlex-hybrid-reply` + uuid | Средняя |
| 3 | Эвристика «последний pending на ящик» | **Отключить** для email или только с `LOG.warning` (не использовать в проде) |

После сопоставления:

- текст письма (без цитат переписки по возможности — strip quoted reply) → `responses[task_id]`;
- письмо помечается **прочитанным** / переносится в `SUFFLER_IMAP_PROCESSED_FOLDER` (опционально `Sinlex/Done`);
- запись удаляется из `pending`.

**Мультипользователь:** маршрутизация в Sinlex только по **`task_id`** → `hybrid_jobs/{task_id}.json` (поля `user_folder`, `project_name`). Папка клиента на диске **не** берётся из темы письма — только из job.

### 4.5 `parse_response`

Идентично `MaxSufflerBot.parse_response`: Ra, H7, допуски, `notes` без служебных строк `#sinlex-hybrid`, `task_id:`, `project:`.

Допустимо вынести общую функцию в `hybrid_channel_common.py` или импортировать из `max_suffler` без инициализации бота.

---

## 5. Переменные окружения

### 5.1 Общие (без изменений)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `ENABLE_HYBRID_SUFFLER` | `0` | `1` — кнопка «Углублённый анализ» |
| `SUFFLER_TIMEOUT_SECONDS` | `3600` | Таймаут job |
| `SUFFLER_POLL_INTERVAL_SEC` | `15` | Опрос status в UI |
| `HYBRID_CHANNEL_CONFIG` | `config/hybrid_channel.json` | Путь к JSON-переключателю |

### 5.2 Email (`email_logistics`)

| Переменная | Обязательность | Описание |
|------------|----------------|----------|
| `SUFFLER_EMAIL_TO` | да | Адрес получателя задач (технологи) |
| `SUFFLER_EMAIL_FROM` | да | Отправитель (ящик Sinlex) |
| `SUFFLER_SMTP_HOST` | да | SMTP |
| `SUFFLER_SMTP_PORT` | `587` | Порт |
| `SUFFLER_SMTP_USER` | да* | Логин (*если сервер требует) |
| `SUFFLER_SMTP_PASSWORD` | да* | Пароль в `secrets.env` |
| `SUFFLER_SMTP_TLS` | `1` | STARTTLS |
| `SUFFLER_IMAP_HOST` | да | IMAP |
| `SUFFLER_IMAP_PORT` | `993` | Порт |
| `SUFFLER_IMAP_USER` | да | Обычно тот же ящик, что `FROM` |
| `SUFFLER_IMAP_PASSWORD` | да | `secrets.env` |
| `SUFFLER_IMAP_FOLDER` | `INBOX` | Входящие |
| `SUFFLER_IMAP_PROCESSED_FOLDER` | — | Опционально: перенос обработанных |
| `EMAIL_LOGISTICS_STATE_FILE` | `data/email_logistics_state.json` | State pending/responses |

### 5.3 Max (legacy, выключен по умолчанию)

Остаются `MAX_SUFFLER_TOKEN`, `MAX_SUFFLER_CHAT_ID` — нужны только если `active_channel: "max_suffler"`.

Добавить в `secrets.env.example` блок email; Max пометить `# legacy`.

---

## 6. Изменения по файлам

| Артефакт | Действие |
|----------|----------|
| `config/hybrid_channel.json` | **Создать** шаблон в git |
| `email_logistics/*` | **Создать** транспорт |
| `hybrid_analysis.py` | `get_hybrid_channel()`, передача `user_folder` в `send_drawing` |
| `max_suffler.py` | Без удаления; реализует `HybridChannel`; не вызывается при `email_logistics` |
| `hybrid_analysis.run_start_background` | `send_drawing(..., user_folder=job["user_folder"])` |
| `tests/test_email_logistics.py` | **Создать** mock SMTP/IMAP, reply matching |
| `tests/test_hybrid_analysis.py` | Патч `get_hybrid_channel` вместо `get_max_suffler_bot` |
| `README.md` | Раздел каналов + email env |
| `docs/TZ-hybrid-deep-analysis.md` | Ссылка на этот документ; Max как legacy |

**Не менять:** промпт `suffler_text`, LLM-стеки, маркеры Sinlex AI 1.0/1.2, API путей `/hybrid-analysis/*`.

---

## 7. Job и API (расширение)

В `HybridAnalysisJob` добавить (опционально, для отладки):

```json
{
  "channel": "email_logistics",
  "channel_message_id": "<abc@mail.sinlex>",
  "channel_sent_at": "ISO8601"
}
```

Публичный API `job_to_public` **не** отдаёт `channel_message_id` (внутреннее).

---

## 8. UI и ошибки

| Ситуация | UI |
|----------|-----|
| Таймаут `SUFFLER_TIMEOUT_SECONDS` | «Анализ временно недоступен, попробуйте позже» (как сейчас) |
| Отказ SMTP/IMAP/конфиг | «Углублённый анализ недоступен» / config (как Max config) |
| Отказ LLM после ответа | «Сервер анализа временно недоступен» (`LLM_UI_ERROR_MESSAGE`) |

Индикатор ожидания без изменений: spinner до `status=ready`, затем finalize.

---

## 9. Безопасность

1. Пароли только в `secrets.env`, не в `hybrid_channel.json`.
2. TLS для SMTP/IMAP обязателен в проде.
3. В логах не писать тела писем целиком — только `task_id`, `message_id`, длина текста.
4. Rate limit: не чаще 1 IMAP connect на `check_response` × число pending (оптимизация HE-4: один IMAP pass на все pending за тик).

---

## 10. Этапы реализации (HE)

| ID | Содержание | Файлы | Приёмка |
|----|------------|-------|---------|
| **HE-0** | JSON-переключатель + `get_hybrid_channel()` (заглушка) | `email_logistics/config.py`, `config/hybrid_channel.json` | При `max_suffler` поведение как сейчас; при `email_logistics` без env — config error |
| **HE-1** | SMTP send + state `message_id` | `smtp_send.py`, `channel.py` | Юнит-тест: письмо с вложением и маркерами |
| **HE-2** | IMAP receive + match In-Reply-To | `imap_receive.py` | Фикстуры: 2 письма, reply попадает в верный `task_id` |
| **HE-3** | Интеграция `hybrid_analysis` + `user_folder` | `hybrid_analysis.py` | E2E mock: start → ready → finalize |
| **HE-4** | IMAP batch poll, processed folder | `channel.py` | Один IMAP за цикл status для всех pending проекта |
| **HE-5** | README, secrets.example, отключение Max в prod JSON | docs | На стенде только email |
| **HE-6** | Smoke на реальном ящике | — | PDF → письмо → reply → ⚫/🔵 анализ в UI |

---

## 11. Тесты

```bash
cd /opt/sinlex && .conda/envs/sinlex/bin/python -m unittest \
  tests.test_email_logistics tests.test_hybrid_analysis -v
```

Минимум:

- загрузка JSON: неверный `active_channel` → ошибка;
- send: в mock SMTP проверить Subject, body `task_id`, attachment;
- receive: `In-Reply-To` → правильный `task_id`;
- receive: чужой reply не забирает чужой pending;
- hybrid: `get_hybrid_channel` патчится в тестах.

---

## 12. Откат

1. В `hybrid_channel.json`: `"active_channel": "max_suffler"`, `"max_suffler": {"enabled": true}`.
2. `systemctl restart sinlex-server`.
3. Модуль `email_logistics` не удалять — не мешает при выключенном канале.

---

## 13. Критерии готовности релиза

- [x] Код: `email_logistics/`, `get_hybrid_channel()`, `hybrid_analysis` (HE-0…HE-3).
- [ ] На проде `active_channel: email_logistics`, Max `enabled: false`.
- [ ] Два параллельных пользователя: два reply по разным цепочкам → два корректных `suffler_text`.
- [ ] Таймаут 1 ч и poll 15 с работают без изменений.
- [ ] В UI нет слов email / Max / SMTP.
- [ ] `docs/TZ-hybrid-deep-analysis.md` обновлён со ссылкой на HE.

---

## 14. Промпт для агента (HE-0…HE-3)

> Реализуй этапы **HE-0…HE-3** из `docs/TZ-hybrid-email-logistics.md`.  
> Создай `config/hybrid_channel.json`, пакет `email_logistics/`, фасад `get_hybrid_channel()`.  
> Переведи `hybrid_analysis.py` с `get_max_suffler_bot` на канал; в `send_drawing` передавай `user_folder`.  
> Max не удалять; по умолчанию в JSON — `email_logistics`.  
> Тесты: `tests/test_email_logistics.py`, обновить `tests/test_hybrid_analysis.py`.  
> Не менять `expert_analyzer`, промпт suffler, UI-тексты кроме сообщений config.
