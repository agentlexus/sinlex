"""Короткие ops-сообщения через MAX Bot API (platform-api.max.ru)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Dict

import requests

LOG = logging.getLogger("ops_notify")

_SECRETS: Dict[str, str] | None = None
_SEND_TIMEOUT_SEC = 120.0
_SEND_RETRIES = 2
_DEFAULT_API_BASE = "https://platform-api.max.ru"


def _load_secrets() -> Dict[str, str]:
    global _SECRETS
    if _SECRETS is not None:
        return _SECRETS
    out: Dict[str, str] = {}
    path = os.environ.get("SINLEX_SECRETS_FILE", "/opt/sinlex/secrets.env")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
        except OSError as exc:
            LOG.warning("secrets read failed: %s", exc)
    _SECRETS = out
    return out


def _env(name: str) -> str:
    return os.environ.get(name, "").strip() or _load_secrets().get(name, "").strip()


def _enabled() -> bool:
    raw = _env("ENABLE_OPS_NOTIFY") or _env("ENABLE_OPS_TELEGRAM_NOTIFY")
    return raw.lower() in ("1", "true", "yes")


def _chat_id() -> str:
    return _env("OPS_MAX_CHAT_ID") or _env("MAX_SUFFLER_CHAT_ID")


def _api_base() -> str:
    return (_env("MAX_API_BASE") or _DEFAULT_API_BASE).rstrip("/")


def _send_message(text: str) -> None:
    if not _enabled():
        return
    token = _env("MAX_SUFFLER_TOKEN")
    chat_id = _chat_id()
    if not token or not chat_id:
        LOG.debug("ops max notify not configured, skip")
        return
    url = f"{_api_base()}/messages"
    headers = {"Authorization": token}
    params = {"chat_id": chat_id}
    body = {"text": text}
    for attempt in range(_SEND_RETRIES):
        try:
            resp = requests.post(
                url,
                headers=headers,
                params=params,
                json=body,
                timeout=_SEND_TIMEOUT_SEC,
            )
            if resp.status_code == 200:
                return
            LOG.warning(
                "ops max notify failed status=%s body=%s attempt=%d",
                resp.status_code,
                resp.text[:200],
                attempt + 1,
            )
        except requests.RequestException as exc:
            LOG.warning("ops max notify error attempt=%d: %s", attempt + 1, exc)
        if attempt + 1 < _SEND_RETRIES:
            time.sleep(3)


def _fire(text: str) -> None:
    if not _enabled():
        return
    threading.Thread(target=_send_message, args=(text,), daemon=True).start()


def notify_user_registered(email: str) -> None:
    email = (email or "").strip()
    if not email:
        return
    _fire(f"Зарегистрирован новый пользователь {email}")


def notify_flow_activated(user_email: str) -> None:
    user_email = (user_email or "").strip()
    if not user_email:
        return
    _fire(f"Активация потока пользователем {user_email}")
