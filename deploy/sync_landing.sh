#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/opt/sinlex}"
LANDING_SRC="${LANDING_SRC:-$REPO_ROOT/landing/}"
LANDING_DST="${LANDING_DST:-/var/www/landing/}"
WEB_USER="${WEB_USER:-www-data}"
WEB_GROUP="${WEB_GROUP:-www-data}"

if [[ ! -d "$LANDING_SRC" ]]; then
  echo "Landing source not found: $LANDING_SRC" >&2
  exit 1
fi

mkdir -p "$LANDING_DST"

rsync -a --delete \
  --exclude 'index.backup-*.html' \
  --exclude '.git/' \
  "$LANDING_SRC" "$LANDING_DST"

chown -R "$WEB_USER:$WEB_GROUP" "$LANDING_DST"

if command -v nginx >/dev/null 2>&1; then
  nginx -t
fi

echo "Landing synced: $LANDING_SRC -> $LANDING_DST"
