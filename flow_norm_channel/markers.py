"""Маркеры писем канала нормировки «Поток» (2D, отдельно от hybrid)."""

from __future__ import annotations

import re
from typing import Optional

FLOW_NORM_TAG = "#sinlex-flow-norm"
FLOW_NORM_BALANCE_TAG = "#sinlex-flow-norm-balance"
FLOW_NORM_CHAT_TAG = "#sinlex-flow-norm-chat"

_RE_CHAT_ID = re.compile(
    r"chat_id\s*:\s*([0-9a-fA-F-]{8,}(?:-q[0-9a-fA-F]+)?)",
    re.IGNORECASE,
)

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
        FLOW_NORM_TAG,
        f"task_id:{task_id}",
    ]
    if safe_user:
        lines.append(f"user_folder:{safe_user}")
    lines.append(f"project:{safe_project}")
    lines.append("")
    lines.append(
        "Чертёж 2D во вложении. Ответьте в этой цепочке (Reply) текстом распознавания "
        "для нормировки (размеры, Ra, отверстия, допуски, материал)."
    )
    return "\n".join(lines)


def build_balance_inquiry_body(
    project_name: str,
    task_id: str,
    *,
    user_balance: int,
    user_email: str = "",
    user_folder: str = "",
) -> str:
    safe_project = (project_name or "—").replace("\n", " ")[:200]
    lines = [
        FLOW_NORM_BALANCE_TAG,
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
        "Нормировка 2D (страница «Поток»). Чертёж во вложении. "
        "Ответьте в этой цепочке (Reply) одним целым числом — сколько рублей списать."
    )
    lines.append("0 — отказ (недостаточно средств / не запускать).")
    lines.append(
        "Число > 0 — списать столько рублей; затем в этой же цепочке пришлите "
        "текст распознавания чертежа для нормировки."
    )
    return "\n".join(lines)




def build_chat_question_body(
    project_name: str,
    task_id: str,
    chat_id: str,
    question: str,
    *,
    user_folder: str = "",
) -> str:
    safe_project = (project_name or "—").replace("\n", " ")[:200]
    safe_q = (question or "").strip().replace("\n", " ")[:4000]
    lines = [
        FLOW_NORM_CHAT_TAG,
        f"task_id:{task_id}",
        f"chat_id:{chat_id}",
    ]
    if user_folder:
        lines.append(f"user_folder:{user_folder.strip()[:120]}")
    lines.append(f"project:{safe_project}")
    lines.append("")
    lines.append("Уточняющий вопрос по чертежу 2D (страница «Поток»). Чертёж во вложении.")
    lines.append(f"Вопрос: {safe_q}")
    lines.append("")
    lines.append(
        "Ответьте в этой цепочке (Reply) текстом с учётом вопроса и чертежа."
    )
    return "\n".join(lines)


def extract_chat_id_from_text(text: str) -> Optional[str]:
    m = _RE_CHAT_ID.search(text or "")
    return m.group(1).strip() if m else None


def extract_task_id_from_text(text: str) -> Optional[str]:
    m = _RE_TASK_ID.search(text or "")
    return m.group(1).strip() if m else None


def parse_balance_rub_from_text(text: str) -> Optional[int]:
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
    return parse_balance_rub_from_text(text)
