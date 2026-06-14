"""Общие типы и разбор ответа гибридного канала (Max / email)."""

from hybrid_channel.errors import HybridChannelError, MaxSufflerError
from hybrid_channel.markers import (
    HYBRID_REPLY_TAG,
    HYBRID_TAG,
    build_outbound_body,
    extract_task_id_from_text,
)
from hybrid_channel.parse import parse_hybrid_response

__all__ = [
    "HybridChannelError",
    "MaxSufflerError",
    "HYBRID_TAG",
    "HYBRID_REPLY_TAG",
    "build_outbound_body",
    "extract_task_id_from_text",
    "parse_hybrid_response",
]
