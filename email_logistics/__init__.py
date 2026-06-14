"""Гибридный канал: email_logistics и фасад get_hybrid_channel."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from email_logistics.channel import EmailLogisticsChannel
from email_logistics.config import resolve_active_channel
from hybrid_channel.errors import HybridChannelError, MaxSufflerError

__all__ = [
    "EmailLogisticsChannel",
    "HybridChannelError",
    "MaxSufflerError",
    "get_hybrid_channel",
    "resolve_active_channel",
]


@runtime_checkable
class HybridChannel(Protocol):
    def send_balance_inquiry(
        self,
        project_name: str,
        task_id: str,
        *,
        pdf_bytes: bytes,
        user_balance: int,
        user_email: str = "",
        user_folder: str = "",
    ) -> str: ...

    def check_balance_response(self, task_id: str) -> int | None: ...

    def begin_suffler_watch(
        self,
        task_id: str,
        project_name: str,
        *,
        user_folder: str = "",
    ) -> str: ...

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


def get_hybrid_channel(**kwargs: Any) -> HybridChannel:
    """Читает config/hybrid_channel.json и возвращает активный канал."""
    name = resolve_active_channel()
    if name == "email_logistics":
        return EmailLogisticsChannel(**kwargs)
    if name == "max_suffler":
        from max_suffler import MaxSufflerBot

        return MaxSufflerBot(**kwargs)
    raise HybridChannelError("config", f"Unknown channel: {name}")
