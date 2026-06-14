#!/usr/bin/env bash
# Полный (или «лёгкий») бэкап /opt/sinlex → tar.gz → Облако Mail.ru через rclone.
# Требуется: rclone + remote mailru (см. docs/backup-mail-cloud.md)
set -euo pipefail

SINLEX_ROOT="/opt/sinlex"
BACKUP_DIR="${SINLEX_ROOT}/backups"
STAMP=$(date -u +%Y%m%d_%H%M%S)
RCLONE_REMOTE="${RCLONE_REMOTE:-mailru:}"
RCLONE_PATH="${RCLONE_PATH:-sinlex-backups}"
INCLUDE_CONDA=0
LOCAL_ONLY=0
UPLOAD=1

usage() {
  cat <<'EOF'
Usage: backup_sinlex_to_mailcloud.sh [options]

  (default)   архив без .conda + загрузка в mailru:sinlex-backups
  --full      включить .conda (~5 ГБ исходника)
  --local-only только tar.gz в /opt/sinlex/backups, без rclone
  --no-upload только создать архив локально
  -h          справка

Перед первым запуском: docs/backup-mail-cloud.md (пароль для внешнего приложения Mail.ru)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full) INCLUDE_CONDA=1 ;;
    --local-only) LOCAL_ONLY=1; UPLOAD=0 ;;
    --no-upload) UPLOAD=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

mkdir -p "$BACKUP_DIR"
if [[ "$INCLUDE_CONDA" -eq 1 ]]; then
  ARCHIVE="${BACKUP_DIR}/sinlex-full-conda_${STAMP}.tar.gz"
  LABEL="full+conda"
else
  ARCHIVE="${BACKUP_DIR}/sinlex-full_${STAMP}.tar.gz"
  LABEL="full"
fi

echo "=== Sinlex backup (${LABEL}) ${STAMP} ==="
echo "Archive: $ARCHIVE"

TAR_EXCLUDES=(
  --exclude='sinlex/backups/*.tar.gz'
  --exclude='sinlex/__pycache__'
  --exclude='sinlex/**/__pycache__'
  --exclude='sinlex/**/*.pyc'
  --exclude='sinlex/.git'
)
if [[ "$INCLUDE_CONDA" -eq 0 ]]; then
  TAR_EXCLUDES+=(--exclude='sinlex/.conda')
fi

tar -czf "$ARCHIVE" "${TAR_EXCLUDES[@]}" -C /opt sinlex
sha256sum "$ARCHIVE" | tee "${ARCHIVE}.sha256"

{
  echo "Sinlex backup (${LABEL})"
  echo "Host: $(hostname -f 2>/dev/null || hostname)"
  echo "Created: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
  echo "Archive: $(basename "$ARCHIVE")"
  echo "Size bytes: $(stat -c%s "$ARCHIVE")"
  echo "Include conda: $INCLUDE_CONDA"
} > "${ARCHIVE%.tar.gz}.txt"

echo "$ARCHIVE" > "${BACKUP_DIR}/last_backup.txt"
ls -lh "$ARCHIVE" "${ARCHIVE}.sha256"

if [[ "$UPLOAD" -eq 0 ]]; then
  echo "Local only — upload skipped."
  exit 0
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "ERROR: rclone not installed. See docs/backup-mail-cloud.md" >&2
  exit 1
fi

REMOTE="${RCLONE_REMOTE%/}"
DEST="${REMOTE}:${RCLONE_PATH}/"
echo "Uploading to ${DEST} ..."
rclone mkdir "${DEST}" 2>/dev/null || true
rclone copy "$ARCHIVE" "${DEST}" -P --transfers 2 --retries 3
rclone copy "${ARCHIVE}.sha256" "${DEST}" -P
rclone copy "${ARCHIVE%.tar.gz}.txt" "${DEST}" -P

echo "Remote listing:"
rclone ls "${DEST}" | tail -5
echo "Done."
