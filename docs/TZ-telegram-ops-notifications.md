# TZ: Ops-уведомления в Max

## Сообщения

| Событие | Текст |
|---------|--------|
| Регистрация | `Зарегистрирован новый пользователь <email>` |
| Поток | `Активация потока пользователем <user email>` |

## Реализация

- `ops_notify/notify.py` — POST `platform-api.max.ru/messages`
- Ключи: `MAX_SUFFLER_TOKEN`, `MAX_SUFFLER_CHAT_ID`
- Флаг: `ENABLE_OPS_NOTIFY=1`

## Smoke

```bash
python3 scripts/smoke_ops_notify.py
python3 -m unittest tests.test_ops_notify
```
