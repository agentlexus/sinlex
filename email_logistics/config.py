"""Конфигурация канала: hybrid_channel.json + secrets.env."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from hybrid_channel.errors import HybridChannelError

LOG = logging.getLogger("email_logistics.config")

ChannelName = Literal["email_logistics", "max_suffler"]

_DEFAULT_CONFIG_PATH = Path("/opt/sinlex/config/hybrid_channel.json")
_SECRETS: Dict[str, str] | None = None
_CHANNEL_CACHE: ChannelName | None = None


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


def _config_path() -> Path:
    raw = (
        os.environ.get("HYBRID_CHANNEL_CONFIG", "").strip()
        or _load_secrets().get("HYBRID_CHANNEL_CONFIG", "").strip()
    )
    return Path(raw) if raw else _DEFAULT_CONFIG_PATH


def load_channel_config() -> Dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        raise HybridChannelError(
            "config",
            f"HYBRID_CHANNEL_CONFIG not found: {path}",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HybridChannelError(
            "config",
            f"Invalid hybrid channel config: {path}",
            cause=exc,
        ) from exc
    if not isinstance(data, dict):
        raise HybridChannelError("config", "hybrid_channel.json must be an object")
    version = data.get("version")
    if version != 1:
        raise HybridChannelError(
            "config",
            f"Unsupported hybrid_channel.json version: {version!r}",
        )
    return data


def resolve_active_channel(*, force_reload: bool = False) -> ChannelName:
    global _CHANNEL_CACHE
    if _CHANNEL_CACHE is not None and not force_reload:
        return _CHANNEL_CACHE

    data = load_channel_config()
    active = (data.get("active_channel") or "").strip()
    if active not in ("email_logistics", "max_suffler"):
        raise HybridChannelError(
            "config",
            f"Invalid active_channel: {active!r}",
        )
    channels = data.get("channels") or {}
    ch = channels.get(active) if isinstance(channels, dict) else None
    if not isinstance(ch, dict) or not ch.get("enabled", True):
        raise HybridChannelError(
            "config",
            f"Channel {active!r} is disabled in hybrid_channel.json",
        )
    _CHANNEL_CACHE = active  # type: ignore[assignment]
    return active  # type: ignore[return-value]


def env_get(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or _load_secrets().get(name, default).strip()


def email_settings() -> Dict[str, Any]:
    """Параметры SMTP/IMAP (без паролей в логах)."""
    return {
        "to": env_get("SUFFLER_EMAIL_TO"),
        "from": env_get("SUFFLER_EMAIL_FROM"),
        "smtp_host": env_get("SUFFLER_SMTP_HOST"),
        "smtp_port": int(env_get("SUFFLER_SMTP_PORT", "587") or "587"),
        "smtp_user": env_get("SUFFLER_SMTP_USER"),
        "smtp_password": env_get("SUFFLER_SMTP_PASSWORD"),
        "smtp_tls": env_get("SUFFLER_SMTP_TLS", "1").lower() in ("1", "true", "yes"),
        "imap_host": env_get("SUFFLER_IMAP_HOST"),
        "imap_port": int(env_get("SUFFLER_IMAP_PORT", "993") or "993"),
        "imap_user": env_get("SUFFLER_IMAP_USER"),
        "imap_password": env_get("SUFFLER_IMAP_PASSWORD"),
        "imap_folder": env_get("SUFFLER_IMAP_FOLDER", "INBOX") or "INBOX",
        "imap_processed_folder": env_get("SUFFLER_IMAP_PROCESSED_FOLDER"),
    }


def require_email_settings() -> Dict[str, Any]:
    cfg = email_settings()
    missing = [
        k
        for k in ("to", "from", "smtp_host", "smtp_user", "smtp_password", "imap_host", "imap_user", "imap_password")
        if not cfg.get(k)
    ]
    if missing:
        raise HybridChannelError(
            "config",
            f"Email channel missing env: {', '.join(missing)}",
        )
    return cfg


def state_file_path() -> Path:
    raw = env_get("EMAIL_LOGISTICS_STATE_FILE", "/opt/sinlex/data/email_logistics_state.json")
    return Path(raw)
