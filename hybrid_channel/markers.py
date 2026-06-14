"""Маркеры в теле писем / сообщений гибридного канала."""

from __future__ import annotations

import re
from typing import Optional

HYBRID_TAG = "#sinlex-hybrid"
HYBRID_REPLY_TAG = "#sinlex-hybrid-reply"
HYBRID_BALANCE_TAG = "#sinlex-flow-balance"

_RE_TASK_ID = re.compile(
    r"task_id\s*:\s*([0-9a-fA-F-]{8,})",
    re.IGNORECASE,
)
_RE_BALANCE_RUB = re.compile(
    r"(?:rub|руб(?:лей)?|₽|списать)\s*[:=]\s*(\d+)",
    re.IGNORECASE,
)
_RE_BALANCE_TOKENS = re.compile(
    r"(?:tokens|токен(?:ов)?)\s*[:=]\s*(\d+)",
    re.IGNORECASE,
)


def build_outbound_body(
    project_name: str,
    task_id: str,
    *,
    user_folder: str = "",
) -> str:
    safe_project = (project_name or "—").replace("\n", " ")[:200]
    safe_user = (user_folder or "").replace("\n", " ")[:120]
    lines = [
        HYBRID_TAG,
        f"task_id:{task_id}",
    ]
    if safe_user:
        lines.append(f"user_folder:{safe_user}")
    lines.append(f"project:{safe_project}")
    lines.append("")
    lines.append(
        "Чертёж во вложении. Ответьте в этой цепочке (Reply) текстом распознавания."
    )
    return "\n".join(lines)


def build_balance_inquiry_body(
    project_name: str,
    task_id: str,
    *,
    user_balance: int,  # рубли
    user_email: str = "",
    user_folder: str = "",
) -> str:
    """Служебное письмо: баланс (₽) + чертёж → ответ = сумма к списанию в рублях."""
    safe_project = (project_name or "—").replace("\n", " ")[:200]
    lines = [
        HYBRID_BALANCE_TAG,
        f"task_id:{task_id}",
        f"balance_rub:{int(user_balance)}",
    ]
    if user_email:
        lines.append(f"user_email:{user_email.strip()[:200]}")
    if user_folder:
        lines.append(f"user_folder:{user_folder.strip()[:120]}")
    lines.append(f"project:{safe_project}")
    lines.append("")
    lines.append(
        "Чертёж во вложении. Ответьте в этой цепочке (Reply) одним целым числом — "
        "сколько рублей списать за углублённый анализ этого чертежа."
    )
    lines.append("0 — отказ (недостаточно средств / анализ не запускать).")
    lines.append(
        "Число > 0 — списать столько рублей; затем в этой же цепочке пришлите "
        "текст распознавания чертежа (как для углублённого анализа)."
    )
    return "\n".join(lines)


def extract_task_id_from_text(text: str) -> Optional[str]:
    m = _RE_TASK_ID.search(text or "")
    return m.group(1).strip() if m else None


def parse_balance_rub_from_text(text: str) -> Optional[int]:
    """Сумма в рублях к списанию из ответа на служебное письмо."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _RE_BALANCE_RUB.search(raw)
    if m:
        return int(m.group(1))
    m = _RE_BALANCE_TOKENS.search(raw)
    if m:
        return int(m.group(1)) * 10
    stripped = raw.splitlines()[0].strip() if raw.splitlines() else raw
    if re.fullmatch(r"\d+", stripped):
        return int(stripped)
    if len(raw) > 80 or raw.count("\n") > 2:
        return None
    return None


def parse_balance_tokens_from_text(text: str) -> Optional[int]:
    """Совместимость: сумма списания в рублях."""
    return parse_balance_rub_from_text(text)
