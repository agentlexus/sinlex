"""Ошибки гибридного канала (Max, email_logistics)."""

from __future__ import annotations

from typing import Optional


def default_ui_message(code: str) -> str:
    if code == "config":
        return "Углублённый анализ недоступен: не настроен доступ."
    return "Углублённый анализ временно недоступен. Попробуйте позже."


class HybridChannelError(Exception):
    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        ui_message: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.code = code
        self.ui_message = ui_message or default_ui_message(code)
        super().__init__(message or self.ui_message)
        self.__cause__ = cause

    @property
    def internal_code(self) -> str:
        return "hybrid_channel" if self.code != "config" else self.code


class MaxSufflerError(HybridChannelError):
    """Обратная совместимость с max_suffler."""
