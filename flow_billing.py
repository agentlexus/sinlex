"""Биллинг «Поток» (legacy pending после пополнения)."""
from __future__ import annotations

import logging

import payment as pay

LOG = logging.getLogger("flow_billing")


def run_flow_billing_gate(
    *,
    user_email: str,
    user_folder: str,
    task_id: str,
    project_name: str,
    analysis_result: dict,
    job: dict,
) -> dict:
    """Устарело: списание до отправки чертежа. Только очередь pending для старых job."""
    pending_entry = pay.find_flow_pending_by_task_id(user_email, task_id)
    if not pending_entry:
        out = dict(analysis_result)
        charged = int(job.get("flow_tokens_charged") or 0)
        if charged:
            out["tokens_debited"] = charged
        return {"status": "ok", "result": out, "tokens_debited": charged}

    balance = pay.get_flow_token_balance(user_email)
    return {
        "status": "pending_payment",
        "rub_required": int(pending_entry.get("rub_required") or 0),
        "balance": balance,
        "pending_id": pending_entry.get("pending_id") or "",
        "ui_message": (
            f"Анализ «Поток» выполнен. Для просмотра пополните баланс: "
            f"нужно **{pending_entry.get('rub_required')}** ₽, на счёте **{balance}**."
        ),
    }
