#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/opt/sinlex}"
BRANCH="${BRANCH:-main}"
GIT_KEY="${GIT_KEY:-/opt/sinlex/.ssh/github_ed25519}"
LOCK_FILE="${LOCK_FILE:-/tmp/sinlex-deploy.lock}"
DEPLOY_USER="${DEPLOY_USER:-sinlex}"
SERVICES=(sinlex-server.service sinlex-streamlit.service)

exec 9>"$LOCK_FILE"
echo "Waiting for deploy lock..."
if ! flock -w "${LOCK_TIMEOUT_SECONDS:-600}" 9; then
  echo "Another Sinlex deploy is still running after ${LOCK_TIMEOUT_SECONDS:-600}s" >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "deploy_server.sh must be run as root" >&2
  exit 1
fi

cd "$REPO_ROOT"

if [[ ! -d .git ]]; then
  echo "Git repository not found at $REPO_ROOT" >&2
  exit 1
fi

export GIT_SSH_COMMAND="ssh -i $GIT_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

echo "Fetching origin/$BRANCH..."
sudo -u "$DEPLOY_USER" env GIT_SSH_COMMAND="$GIT_SSH_COMMAND" git fetch origin "$BRANCH"

local_rev=$(sudo -u "$DEPLOY_USER" git rev-parse HEAD)
remote_rev=$(sudo -u "$DEPLOY_USER" git rev-parse "origin/$BRANCH")

if [[ "$local_rev" == "$remote_rev" && "${SINLEX_DEPLOY_FORCE:-0}" != "1" ]]; then
  echo "No deploy needed: local HEAD already matches origin/$BRANCH (${local_rev:0:7})"
  exit 0
fi

echo "Resetting $REPO_ROOT to origin/$BRANCH..."
sudo -u "$DEPLOY_USER" git reset --hard "origin/$BRANCH"

echo "Syncing landing..."
"$REPO_ROOT/deploy/sync_landing.sh"

echo "Validating nginx..."
nginx -t

echo "Restarting Sinlex services..."
systemctl daemon-reload
for service in "${SERVICES[@]}"; do
  systemctl restart "$service"
  systemctl is-active --quiet "$service"
  echo "$service is active"
done

deployed_rev=$(sudo -u "$DEPLOY_USER" git rev-parse --short HEAD)
echo "Sinlex deploy complete: $deployed_rev"
