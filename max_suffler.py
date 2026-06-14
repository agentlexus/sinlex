"""
Клиент гибридного углублённого анализа через MAX Bot API.

Документация API: https://dev.max.ru/docs-api
Альтернатива (не в зависимостях): https://pypi.org/project/maxapi/

Протокол (v1):
- send_drawing: PDF + метка task_id в тексте сообщения;
- check_response: опрос GET /updates, ответ — reply на сообщение с PDF или текст с task_id.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from hybrid_channel.errors import MaxSufflerError
from hybrid_channel.markers import (
    HYBRID_BALANCE_TAG,
    HYBRID_REPLY_TAG,
    HYBRID_TAG,
    build_balance_inquiry_body,
    build_outbound_body,
)
from hybrid_channel.parse import parse_hybrid_response

LOG = logging.getLogger("max_suffler")

# Обратная совместимость импортов
_HYBRID_TAG = HYBRID_TAG
_HYBRID_REPLY_TAG = HYBRID_REPLY_TAG

_FORBIDDEN_UI_WORDS = (
    "суфлер",
    "suffler",
    "эксперт",
    "технолог",
    "помощник",
    "внешний канал",
    "бот макс",
    "max bot",
)


def _load_secrets() -> Dict[str, str]:
    out: Dict[str, str] = {}
    path = os.environ.get("SINLEX_SECRETS_FILE", "/opt/sinlex/secrets.env")
    if not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


_SECRETS = _load_secrets()


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, _SECRETS.get(name, default)).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def hybrid_suffler_enabled() -> bool:
    return _env_bool("ENABLE_HYBRID_SUFFLER", "0")


def _assert_ui_safe(text: str) -> None:
    low = text.lower()
    for word in _FORBIDDEN_UI_WORDS:
        if word in low:
            raise ValueError(f"UI message contains forbidden term: {word!r}")


def _resolve_token(token: Optional[str]) -> str:
    if token:
        return token.strip()
    return (
        os.environ.get("MAX_SUFFLER_TOKEN", "").strip()
        or _SECRETS.get("MAX_SUFFLER_TOKEN", "").strip()
    )


def _resolve_chat_id(chat_id: Optional[int]) -> Optional[int]:
    if chat_id is not None:
        return int(chat_id)
    raw = (
        os.environ.get("MAX_SUFFLER_CHAT_ID", "").strip()
        or _SECRETS.get("MAX_SUFFLER_CHAT_ID", "").strip()
    )
    if not raw:
        return None
    low = raw.lower()
    if "@" in raw or "_bot" in low:
        raise MaxSufflerError(
            "config",
            "MAX_SUFFLER_CHAT_ID must be numeric chat id (see data/max_cdw_bot_state.json chat_id), not bot @id",
        )
    if raw.lstrip("-").isdigit():
        return int(raw)
    raise MaxSufflerError(
        "config",
        "MAX_SUFFLER_CHAT_ID must be a numeric chat id",
    )


def _state_path() -> Path:
    raw = os.environ.get(
        "HYBRID_SUFFLER_STATE_FILE",
        "/opt/sinlex/data/hybrid_suffler_state.json",
    ).strip()
    return Path(raw)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MaxSufflerBot:
    """Отправка чертежа в MAX и ожидание текстового ответа по task_id."""

    def __init__(
        self,
        token: str | None = None,
        *,
        chat_id: int | None = None,
        api_base: str | None = None,
        state_path: Path | str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.token = _resolve_token(token)
        self.chat_id = _resolve_chat_id(chat_id)
        self.api_base = (
            (api_base or os.environ.get("MAX_API_BASE") or "https://platform-api.max.ru")
        ).rstrip("/")
        self.state_path = Path(state_path) if state_path else _state_path()
        self.session = session or requests.Session()
        if self.token:
            self.session.headers["Authorization"] = self.token
    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.is_file():
            return {"marker": None, "pending": {}, "responses": {}, "balance_pending": {}, "balance_responses": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("pending", {})
                data.setdefault("responses", {})
                data.setdefault("balance_pending", {})
                data.setdefault("balance_responses", {})
                data.setdefault("inquiry_meta", {})
                return data
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("hybrid state read failed: %s", exc)
        return {"marker": None, "pending": {}, "responses": {}, "balance_pending": {}, "balance_responses": {}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    def _api(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> requests.Response:
        url = f"{self.api_base}{path}"
        try:
            return self.session.request(method, url, timeout=120, **kwargs)
        except requests.RequestException as exc:
            raise MaxSufflerError(
                "network",
                f"MAX API request failed: {method} {path}",
                cause=exc,
            ) from exc

    def _api_json(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        resp = self._api(method, path, **kwargs)
        if resp.status_code >= 400:
            body = (resp.text or "")[:200]
            LOG.error(
                "hybrid_channel api %s %s status=%s body=%s",
                method,
                path,
                resp.status_code,
                body,
            )
            raise MaxSufflerError(
                "api",
                f"MAX API {method} {path} -> {resp.status_code}",
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise MaxSufflerError("api", "Invalid JSON from MAX API", cause=exc) from exc

    def _require_chat_id(self) -> int:
        if self.chat_id is None:
            raise MaxSufflerError(
                "config",
                "MAX_SUFFLER_CHAT_ID is not set",
            )
        return self.chat_id

    def _upload_pdf_token(self, pdf_bytes: bytes, filename: str) -> str:
        meta = self._api_json("POST", "/uploads", params={"type": "file"})
        upload_url = (meta.get("url") or "").strip()
        if not upload_url:
            raise MaxSufflerError("api", "MAX /uploads returned no url")
        try:
            up = requests.post(
                upload_url,
                files={"data": (filename, pdf_bytes, "application/pdf")},
                timeout=300,
            )
        except requests.RequestException as exc:
            raise MaxSufflerError("network", "PDF upload failed", cause=exc) from exc
        if up.status_code >= 400:
            LOG.error("hybrid_channel pdf upload status=%s", up.status_code)
            raise MaxSufflerError("api", f"PDF upload failed: {up.status_code}")
        try:
            data = up.json()
        except ValueError as exc:
            raise MaxSufflerError("api", "Invalid upload response", cause=exc) from exc
        token = (data.get("token") or "").strip()
        if not token:
            raise MaxSufflerError("api", "PDF upload returned no token")
        return token

    def _send_file_message(
        self,
        chat_id: int,
        text: str,
        file_token: str,
    ) -> Dict[str, Any]:
        body = {
            "text": text,
            "attachments": [{"type": "file", "payload": {"token": file_token}}],
        }
        for attempt in range(6):
            resp = self._api(
                "POST",
                "/messages",
                params={"chat_id": chat_id},
                json=body,
            )
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise MaxSufflerError("api", "Invalid JSON from MAX API", cause=exc) from exc
            try:
                err = resp.json()
            except ValueError:
                err = {}
            if err.get("code") == "attachment.not.ready" and attempt < 5:
                time.sleep(1.5 * (attempt + 1))
                continue
            body = (resp.text or "")[:300]
            LOG.error(
                "hybrid_channel send message status=%s chat_id=%s body=%s",
                resp.status_code,
                chat_id,
                body,
            )
            raise MaxSufflerError(
                "api",
                f"MAX API POST /messages -> {resp.status_code}",
            )
        raise MaxSufflerError("api", "Failed to send message with attachment")


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
        """MAX: чертёж + служебный текст; авто-ответ 10 ₽ при balance>0."""
        if not self.token:
            raise MaxSufflerError("config", "MAX_SUFFLER_TOKEN is not set")
        if not pdf_bytes:
            raise MaxSufflerError("api", "Empty PDF payload")
        tid = (task_id or "").strip()
        if not tid:
            raise MaxSufflerError("api", "task_id is required")
        chat_id = self._require_chat_id()
        tokens = 10 if int(user_balance) > 0 else 0  # ₽ к списанию
        state = self._load_state()
        state.setdefault("balance_pending", {})[tid] = {
            "sent_at": _now_iso(),
            "user_balance": int(user_balance),
            "chat_id": chat_id,
        }
        state.setdefault("balance_responses", {})[tid] = tokens
        state.get("balance_pending", {}).pop(tid, None)
        state.setdefault("inquiry_meta", {})[tid] = {
            "message_id": "",
            "project_name": project_name,
            "user_folder": user_folder,
            "chat_id": chat_id,
        }
        self._save_state(state)
        filename = "drawing.pdf"
        file_token = self._upload_pdf_token(pdf_bytes, filename)
        from hybrid_channel.markers import build_balance_inquiry_body

        text = build_balance_inquiry_body(
            project_name,
            tid,
            user_balance=int(user_balance),
            user_email=user_email,
            user_folder=user_folder,
        )
        result = self._send_file_message(chat_id, text, file_token)
        msg = result.get("message") or result
        body = (msg.get("body") or {}) if isinstance(msg, dict) else {}
        mid = (body.get("mid") or "").strip()
        state = self._load_state()
        if tid in state.get("inquiry_meta", {}):
            state["inquiry_meta"][tid]["message_id"] = mid
        self._save_state(state)
        LOG.info(
            "hybrid_channel balance+pdf task_id=%s balance=%s tokens=%s mid=%s",
            tid,
            user_balance,
            tokens,
            mid or "—",
        )
        return tid

    def begin_suffler_watch(
        self,
        task_id: str,
        project_name: str,
        *,
        user_folder: str = "",
    ) -> str:
        tid = (task_id or "").strip()
        if not tid:
            raise MaxSufflerError("api", "task_id is required")
        chat_id = self._require_chat_id()
        state = self._load_state()
        meta = (state.get("inquiry_meta") or {}).pop(tid, {}) or {}
        pending_map = state.setdefault("pending", {})
        pending_map[tid] = {
            "project_name": project_name,
            "message_id": meta.get("message_id") or "",
            "chat_id": int(meta.get("chat_id") or chat_id),
            "sent_at": _now_iso(),
        }
        state.setdefault("responses", {}).pop(tid, None)
        self._save_state(state)
        return tid

    def check_balance_response(self, task_id: str) -> int | None:
        tid = (task_id or "").strip()
        if not tid:
            return None
        state = self._load_state()
        cached = (state.get("balance_responses") or {}).get(tid)
        if cached is not None:
            return int(cached)
        if tid in (state.get("balance_pending") or {}):
            return None
        return None

    def send_drawing(
        self,
        pdf_bytes: bytes,
        project_name: str,
        task_id: str,
        *,
        user_folder: str = "",
    ) -> str:
        """
        Отправляет PDF в чат MAX. Возвращает task_id (тот же, что передан).
        """
        if not self.token:
            raise MaxSufflerError("config", "MAX_SUFFLER_TOKEN is not set")
        if not pdf_bytes:
            raise MaxSufflerError("api", "Empty PDF payload")
        chat_id = self._require_chat_id()
        tid = (task_id or "").strip()
        if not tid:
            raise MaxSufflerError("api", "task_id is required")

        # Регистрируем pending до HTTP (LP-4): опрос /updates не должен идти «в пустоту»
        # и сдвигать marker до появления task_id в state.
        state = self._load_state()
        pending_map: Dict[str, Dict[str, Any]] = state.setdefault("pending", {})
        for other_tid, item in list(pending_map.items()):
            if other_tid == tid:
                continue
            if int(item.get("chat_id") or 0) == int(chat_id):
                pending_map.pop(other_tid, None)
        pending_map[tid] = {
            "project_name": project_name,
            "message_id": "",
            "chat_id": chat_id,
            "sent_at": _now_iso(),
        }
        state.setdefault("responses", {}).pop(tid, None)
        self._save_state(state)

        filename = "drawing.pdf"
        file_token = self._upload_pdf_token(pdf_bytes, filename)
        text = build_outbound_body(project_name, tid, user_folder=user_folder)
        result = self._send_file_message(chat_id, text, file_token)
        msg = result.get("message") or result
        body = (msg.get("body") or {}) if isinstance(msg, dict) else {}
        mid = (body.get("mid") or "").strip()

        state = self._load_state()
        if tid in state.get("pending", {}):
            state["pending"][tid]["message_id"] = mid
        self._save_state(state)
        LOG.info(
            "hybrid_channel sent task_id=%s project=%s pdf_bytes=%s mid=%s",
            tid,
            (project_name or "")[:80],
            len(pdf_bytes),
            mid or "—",
        )
        return tid

    def _poll_updates(self, state: Dict[str, Any]) -> None:
        params: Dict[str, Any] = {
            "timeout": 2,
            "limit": 100,
            "types": "message_created",
        }
        marker = state.get("marker")
        if marker is not None:
            params["marker"] = marker
        data = self._api_json("GET", "/updates", params=params)
        if data.get("marker") is not None:
            state["marker"] = data["marker"]
        for upd in data.get("updates") or []:
            if (upd.get("update_type") or "") != "message_created":
                continue
            self._try_capture_reply(state, upd)

    @staticmethod
    def _is_outbound_bot_message(msg: Dict[str, Any], text: str) -> bool:
        sender = msg.get("sender") or {}
        if sender.get("is_bot"):
            return True
        if text.startswith(_HYBRID_TAG) or text.startswith(HYBRID_BALANCE_TAG):
            return True
        if "task_id:" in text and _HYBRID_TAG in text:
            return True
        return False

    def _pick_pending_for_plain_text(
        self,
        pending: Dict[str, Dict[str, Any]],
        chat_id: Optional[int],
    ) -> Optional[str]:
        """Ответ без reply в MAX — привязка к последнему ожидающему task в этом чате."""
        candidates: List[Tuple[str, str]] = []
        for tid, item in pending.items():
            if chat_id is not None and int(item.get("chat_id") or 0) != int(chat_id):
                continue
            candidates.append((tid, item.get("sent_at") or ""))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1])
        return candidates[-1][0]

    def _try_capture_reply(self, state: Dict[str, Any], update: Dict[str, Any]) -> None:
        msg = update.get("message") or {}
        recipient = msg.get("recipient") or {}
        chat_id = recipient.get("chat_id")
        if self.chat_id and chat_id and int(chat_id) != int(self.chat_id):
            return

        body = msg.get("body") or {}
        text = (body.get("text") or "").strip()
        if not text:
            return
        if self._is_outbound_bot_message(msg, text):
            return

        link = msg.get("link") or {}
        linked = (link.get("message") or {}) if isinstance(link, dict) else {}
        reply_mid = (linked.get("mid") or "").strip()

        pending: Dict[str, Dict[str, Any]] = state.get("pending") or {}
        if not pending:
            return
        responses: Dict[str, str] = state.setdefault("responses", {})

        matched_tid: Optional[str] = None
        if reply_mid:
            for tid, item in pending.items():
                if (item.get("message_id") or "") == reply_mid:
                    matched_tid = tid
                    break

        if matched_tid is None:
            for tid in pending:
                if f"task_id:{tid}" in text or f"task_id: {tid}" in text:
                    matched_tid = tid
                    break
                if text.startswith(_HYBRID_REPLY_TAG) and tid in text:
                    matched_tid = tid
                    break

        if matched_tid is None:
            matched_tid = self._pick_pending_for_plain_text(pending, chat_id)

        if not matched_tid:
            return

        responses[matched_tid] = text
        pending.pop(matched_tid, None)
        LOG.info(
            "hybrid_channel response task_id=%s chars=%s reply_mid=%s",
            matched_tid,
            len(text),
            reply_mid or "—",
        )

    def check_response(self, task_id: str) -> str | None:
        """Текст ответа или None, если ещё не готов."""
        tid = (task_id or "").strip()
        if not tid:
            return None
        state = self._load_state()
        cached = (state.get("responses") or {}).get(tid)
        if cached:
            return cached
        pending = state.get("pending") or {}
        if tid not in pending:
            # Не опрашиваем /updates, пока send_drawing не зарегистрировал task (LP-4).
            return None
        if not self.token:
            return None
        self._poll_updates(state)
        self._save_state(state)
        return (state.get("responses") or {}).get(tid)

    def parse_response(self, text: str) -> dict:
        return parse_hybrid_response(text)


def get_max_suffler_bot(**kwargs: Any) -> MaxSufflerBot:
    """Фабрика Max-канала (legacy); при email активен не вызывается."""
    bot = MaxSufflerBot(**kwargs)
    if not bot.token:
        raise MaxSufflerError("config", "MAX_SUFFLER_TOKEN is required")
    if bot.chat_id is None:
        raise MaxSufflerError("config", "MAX_SUFFLER_CHAT_ID is required")
    return bot
