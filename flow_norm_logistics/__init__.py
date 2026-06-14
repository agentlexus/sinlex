"""Канал нормировки «Поток» (email, отдельно от get_hybrid_channel)."""

from __future__ import annotations

from typing import Any

from flow_norm_logistics.channel import FlowNormEmailChannel
from hybrid_channel.errors import HybridChannelError, MaxSufflerError

__all__ = [
    "FlowNormEmailChannel",
    "HybridChannelError",
    "MaxSufflerError",
    "get_flow_norm_channel",
]


def get_flow_norm_channel(**kwargs: Any) -> FlowNormEmailChannel:
    return FlowNormEmailChannel(**kwargs)
