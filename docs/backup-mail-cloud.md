# Полный бэкап Sinlex в Облако Mail.ru

## Размеры (ориентир)

| Что архивировать | Размер на диске | Архив (примерно) |
|------------------|-----------------|------------------|
| **Код + projects + data** (без `.conda`) | ~140 МБ | **80–150 МБ** `.tar.gz` |
| **Всё `/opt/sinlex`** (с conda/OCC) | ~5.1 ГБ | **2–4 ГБ** `.tar.gz` |

Для облака обычно достаточно **без `.conda`**: окружение восстанавливается скриптами `scripts/install_occ_env.sh`, `scripts/install_drawing_ocr.sh`.

На VPS сейчас свободно ~12 ГБ — полный архив с conda помещается локально, но загрузка в облако дольше.

---

## Шаг 1. Пароль для внешнего приложения (Mail.ru)

Обычный пароль от почты **не подойдёт**.

1. Войти на https://cloud.mail.ru (или mail.ru → Облако).
2. Иконка профиля → **Пароль и безопасность** → **Пароли для внешних приложений**.
3. Создать пароль, имя например `rclone-sinlex-backup`.
4. Права: **«Полный доступ к Почте, Облаку и Календарю»** (для rclone так надёжнее, чем только WebDAV).
5. Скопировать пароль — показывается один раз.

Справка Mail: https://help.mail.ru/cloud/desktop/webdav/

---

## Шаг 2. Установить rclone на VPS

```bash
curl -fsSL https://rclone.org/install.sh | sudo bash
rclone version
```

---

## Шаг 3. Настроить remote `mailru`

```bash
rclone config
```

- `n` — new remote  
- `name` → `mailru`  
- `Storage` → **mailru** (Mail.ru Cloud)  
- `user` → `ваш@email.ru`  
- `pass` → **пароль для внешнего приложения** (не основной пароль)  
- остальное — Enter по умолчанию  

Проверка:

```bash
rclone lsd mailru:
rclone mkdir mailru:sinlex-backups   # один раз
```

Документация rclone: https://rclone.org/mailru/

---

## Шаг 4. Создать архив и загрузить

### Автоматически (скрипт в репозитории)

```bash
# только код и данные (рекомендуется)
/opt/sinlex/scripts/backup_sinlex_to_mailcloud.sh

# с conda (большой архив, долго)
/opt/sinlex/scripts/backup_sinlex_to_mailcloud.sh --full
```

Переменные (при необходимости):

```bash
export RCLONE_REMOTE=mailru:
export RCLONE_PATH=sinlex-backups
```

### Вручную

```bash
STAMP=$(date -u +%Y%m%d_%H%M%S)
ARCHIVE="/opt/sinlex/backups/sinlex-full_${STAMP}.tar.gz"

tar -czf "$ARCHIVE" \
  --exclude='.conda' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='backups/*.tar.gz' \
  -C /opt sinlex

sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"

rclone copy "$ARCHIVE" "mailru:sinlex-backups/" -P --transfers 2
rclone copy "${ARCHIVE}.sha256" "mailru:sinlex-backups/" -P
```

---

## Шаг 5. Проверка в облаке

```bash
rclone ls mailru:sinlex-backups/
```

В браузере: https://cloud.mail.ru → папка `sinlex-backups`.

---

## Восстановление

```bash
rclone copy mailru:sinlex-backups/sinlex-full_YYYYMMDD_HHMMSS.tar.gz /tmp/
cd /tmp && sha256sum -c sinlex-full_YYYYMMDD_HHMMSS.tar.gz.sha256
tar -xzf sinlex-full_YYYYMMDD_HHMMSS.tar.gz -C /opt
# при архиве без .conda:
cd /opt/sinlex && bash scripts/install_occ_env.sh
systemctl restart sinlex-server sinlex-streamlit
```

---

## Альтернатива без rclone

1. На VPS: `backup_sinlex_to_mailcloud.sh --local-only` (только tar в `/opt/sinlex/backups`).
2. Скачать `.tar.gz` на ПК: `scp root@VPS:/opt/sinlex/backups/sinlex-full_*.tar.gz .`
3. Загрузить файл в Облако через сайт или приложение **Облако Mail.ru**.

---

## Cron (раз в неделю, после настройки rclone)

```cron
0 3 * * 0 root /opt/sinlex/scripts/backup_sinlex_to_mailcloud.sh >> /var/log/sinlex-backup.log 2>&1
```
