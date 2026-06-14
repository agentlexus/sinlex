"""Email-канал нормировки «Поток» (отдельное состояние от email_logistics)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from flow_norm_logistics.config import email_settings, require_email_settings, state_file_path
from flow_norm_logistics.imap_receive import poll_balance_inbox, poll_chat_inbox, poll_inbox
from flow_norm_logistics.smtp_send import (
    send_balance_inquiry_email,
    send_chat_question_email,
    send_drawing_email,
)
from hybrid_channel.errors import HybridChannelError
from hybrid_channel.parse import parse_hybrid_response

LOG = logging.getLogger("flow_norm_logistics.channel")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_state() -> Dict[str, Any]:
    return {
        "pending": {},
        "responses": {},
        "balance_pending": {},
        "balance_responses": {},
        "inquiry_meta": {},
        "chat_pending": {},
        "chat_responses": {},
    }


class FlowNormEmailChannel:
    """SMTP/IMAP для страницы «Поток» — не смешивается с hybrid_jobs / email_logistics state."""

    def __init__(self, *, state_path: Path | None = None) -> None:
        self.state_path = state_path or state_file_path()
        require_email_settings()

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.is_file():
            return _empty_state()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in _empty_state():
                    data.setdefault(key, {})
                return data
        except (OSError, ValueError) as exc:
            LOG.warning("flow_norm state read failed: %s", exc)
        return _empty_state()

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def send_balance_inquiry(
        self,
        project_name: str,
        task_id: str,
        *,
        pdf_bytes: bytes,
        user_balance: int,
        user_email: str = "",
        user_folder: str = "",
    ) -> str:
        tid = (task_id or "").strip()
        if not tid:
            raise HybridChannelError("api", "task_id is required")
        if not pdf_bytes:
            raise HybridChannelError("api", "Empty PDF payload")

        state = self._load_state()
        balance_pending = state.setdefault("balance_pending", {})
        balance_pending[tid] = {
            "message_id": "",
            "sent_at": _now_iso(),
            "user_folder": user_folder or "",
            "project_name": project_name or "",
            "user_balance": int(user_balance),
        }
        state.setdefault("balance_responses", {}).pop(tid, None)
        state.setdefault("inquiry_meta", {}).pop(tid, None)
        self._save_state(state)

        cfg = email_settings()
        message_id, _subject = send_balance_inquiry_email(
            cfg,
            pdf_bytes=pdf_bytes,
            project_name=project_name,
            task_id=tid,
            user_balance=int(user_balance),
            user_email=user_email,
            user_folder=user_folder,
        )

        state = self._load_state()
        if tid in state.get("balance_pending", {}):
            state["balance_pending"][tid]["message_id"] = message_id
        self._save_state(state)
        return tid

    def check_balance_response(self, task_id: str) -> Optional[int]:
        tid = (task_id or "").strip()
        if not tid:
            return None

        state = self._load_state()
        cached = (state.get("balance_responses") or {}).get(tid)
        if cached is not None:
            return int(cached)

        balance_pending = state.get("balance_pending") or {}
        if tid not in balance_pending:
            return None

        try:
            poll_balance_inbox(email_settings(), state)
        except HybridChannelError:
            raise
        except Exception as exc:
            raise HybridChannelError("network", "IMAP poll failed", cause=exc) from exc

        self._save_state(state)
        cached = (state.get("balance_responses") or {}).get(tid)
        if cached is None:
            return None
        return int(cached)

    def begin_suffler_watch(
        self,
        task_id: str,
        project_name: str,
        *,
        user_folder: str = "",
    ) -> str:
        tid = (task_id or "").strip()
        if not tid:
            raise HybridChannelError("api", "task_id is required")

        state = self._load_state()
        meta = (state.get("inquiry_meta") or {}).pop(tid, None)
        if not meta:
            bal = (state.get("balance_pending") or {}).get(tid) or {}
            meta = {
                "message_id": bal.get("message_id") or "",
                "project_name": project_name or bal.get("project_name") or "",
                "user_folder": user_folder or bal.get("user_folder") or "",
            }

        pending = state.setdefault("pending", {})
        pending[tid] = {
            "message_id": meta.get("message_id") or "",
            "sent_at": _now_iso(),
            "user_folder": user_folder or meta.get("user_folder") or "",
            "project_name": project_name or meta.get("project_name") or "",
        }
        state.setdefault("responses", {}).pop(tid, None)
        self._save_state(state)
        return tid

    def check_response(self, task_id: str) -> str | None:
        tid = (task_id or "").strip()
        if not tid:
            return None

        state = self._load_state()
        cached = (state.get("responses") or {}).get(tid)
        if cached:
            return cached

        pending = state.get("pending") or {}
        if tid not in pending:
            return None

        try:
            poll_inbox(email_settings(), state)
        except HybridChannelError:
            raise
        except Exception as exc:
            raise HybridChannelError("network", "IMAP poll failed", cause=exc) from exc

        self._save_state(state)
        return (state.get("responses") or {}).get(tid)

    def parse_response(self, text: str) -> dict:
        return parse_hybrid_response(text)
    def send_chat_question(
        self,
        project_name: str,
        task_id: str,
        *,
        chat_id: str,
        question: str,
        drawing_bytes: bytes,
        drawing_filename: str,
        reply_to_message_id: str = "",
        user_folder: str = "",
    ) -> str:
        cid = (chat_id or "").strip()
        if not cid:
            raise HybridChannelError("api", "chat_id is required")
        if not drawing_bytes:
            raise HybridChannelError("api", "Empty drawing payload")
        state = self._load_state()
        chat_pending = state.setdefault("chat_pending", {})
        chat_pending[cid] = {
            "message_id": "",
            "thread_message_id": reply_to_message_id or "",
            "sent_at": _now_iso(),
            "master_task_id": task_id,
            "project_name": project_name or "",
        }
        state.setdefault("chat_responses", {}).pop(cid, None)
        self._save_state(state)
        cfg = email_settings()
        message_id, _subject = send_chat_question_email(
            cfg,
            drawing_bytes=drawing_bytes,
            drawing_filename=drawing_filename,
            project_name=project_name,
            task_id=task_id,
            chat_id=cid,
            question=question,
            reply_to_message_id=reply_to_message_id,
            user_folder=user_folder,
        )
        state = self._load_state()
        if cid in state.get("chat_pending", {}):
            state["chat_pending"][cid]["message_id"] = message_id
        self._save_state(state)
        return cid

    def check_chat_response(self, chat_id: str) -> str | None:
        cid = (chat_id or "").strip()
        if not cid:
            return None
        state = self._load_state()
        cached = (state.get("chat_responses") or {}).get(cid)
        if cached:
            return cached
        if cid not in (state.get("chat_pending") or {}):
            return None
        try:
            poll_chat_inbox(email_settings(), state)
        except HybridChannelError:
            raise
        except Exception as exc:
            raise HybridChannelError("network", "IMAP poll failed", cause=exc) from exc
        self._save_state(state)
        return (state.get("chat_responses") or {}).get(cid)

