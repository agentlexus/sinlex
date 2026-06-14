"""Конфигурация email-канала нормировки «Поток» (отдельное состояние от hybrid)."""

from __future__ import annotations

import os
from pathlib import Path

from email_logistics.config import email_settings, env_get, require_email_settings
from hybrid_channel.errors import HybridChannelError

__all__ = [
    "email_settings",
    "env_get",
    "require_email_settings",
    "state_file_path",
]


def state_file_path() -> Path:
    raw = env_get(
        "FLOW_NORM_EMAIL_STATE_FILE",
        "/opt/sinlex/data/flow_norm_email_state.json",
    )
    return Path(raw)
