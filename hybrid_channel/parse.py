"""Разбор текста ответа внешнего канала."""

from __future__ import annotations

import re
from typing import List

from hybrid_channel.markers import HYBRID_REPLY_TAG, HYBRID_TAG

_RE_RA = re.compile(r"(?:Ra|Rz)\s*(\d+[.,]?\d*)", re.IGNORECASE)
_RE_H = re.compile(r"\bH([6-9]|10|11)\b", re.IGNORECASE)
_RE_TOL = re.compile(r"[±]\s*0?\.\d+|допуск", re.IGNORECASE)


def parse_hybrid_response(text: str) -> dict:
    src = (text or "").strip()
    roughness: List[str] = []
    for m in _RE_RA.finditer(src):
        roughness.append(f"Ra {m.group(1).replace(',', '.')}")
    tolerances: List[str] = []
    for m in _RE_H.finditer(src):
        tolerances.append(f"H{m.group(1)}")
    for m in _RE_TOL.finditer(src):
        span = m.group(0).strip()
        if span and span not in tolerances:
            tolerances.append(span)
    notes = ""
    if HYBRID_REPLY_TAG in src:
        parts = src.split(HYBRID_REPLY_TAG, 1)
        notes = parts[-1].strip()
    elif "task_id:" in src.lower():
        lines = src.splitlines()
        notes = "\n".join(
            ln
            for ln in lines
            if not ln.startswith(HYBRID_TAG)
            and not ln.lower().startswith("task_id:")
            and not ln.lower().startswith("user_folder:")
            and not ln.lower().startswith("project:")
        ).strip()
    else:
        notes = src
    return {
        "roughness": sorted(set(roughness)),
        "tolerances": sorted(set(tolerances))[:50],
        "notes": notes[:8000],
    }
