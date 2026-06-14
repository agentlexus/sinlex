"""IMAP для канала нормировки «Поток» (отдельные маркеры, не hybrid)."""

from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header
from email.message import Message
from typing import Any, Dict, List, Optional, Set

from flow_norm_channel.markers import (
    FLOW_NORM_BALANCE_TAG,
    FLOW_NORM_CHAT_TAG,
    FLOW_NORM_TAG,
    extract_chat_id_from_text,
    extract_task_id_from_text,
    parse_balance_tokens_from_text,
)
from hybrid_channel.errors import HybridChannelError

LOG = logging.getLogger("flow_norm_logistics.imap")

_MSGID_RE = re.compile(r"<([^>]+)>")


def normalize_msg_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    m = _MSGID_RE.search(raw)
    if m:
        return m.group(1).strip().lower()
    return raw.strip("<> \t\r\n").lower()


def _decode_header(value: str) -> str:
    if not value:
        return ""
    parts: List[str] = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _message_body_text(msg: Message) -> str:
    from email_logistics.imap_receive import strip_quoted_reply, _html_to_text

    plain = ""
    html = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ctype == "text/plain" and not plain:
                plain = text
            elif ctype == "text/html" and not html:
                html = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if (msg.get_content_type() or "").lower() == "text/html":
                html = text
            else:
                plain = text
    if plain:
        return strip_quoted_reply(plain)
    if html:
        return strip_quoted_reply(_html_to_text(html))
    return ""


def _header_msg_ids(msg: Message, name: str) -> Set[str]:
    raw = _decode_header(msg.get(name) or "")
    ids: Set[str] = set()
    for token in re.split(r"\s+", raw):
        n = normalize_msg_id(token)
        if n:
            ids.add(n)
    return ids


def _match_task_id(
    pending: Dict[str, Dict[str, Any]],
    msg: Message,
    body: str,
) -> Optional[str]:
    in_reply = _header_msg_ids(msg, "In-Reply-To")
    refs = _header_msg_ids(msg, "References")
    header_ids = in_reply | refs

    if header_ids:
        for tid, item in pending.items():
            mid = normalize_msg_id(str(item.get("message_id") or ""))
            if mid and mid in header_ids:
                return tid

    tid = extract_task_id_from_text(body)
    if tid and tid in pending:
        return tid

    if FLOW_NORM_TAG in body:
        for tid in pending:
            if tid in body:
                return tid

    return None


def _is_outbound_service_body(body: str) -> bool:
    low = (body or "").strip()
    if low.startswith(FLOW_NORM_TAG) and "task_id:" in low.lower():
        return True
    if low.startswith(FLOW_NORM_BALANCE_TAG) and "task_id:" in low.lower():
        return True
    if low.startswith(FLOW_NORM_CHAT_TAG) and "chat_id:" in low.lower():
        return True
    return False


def _imap_connect_and_select(cfg: dict, *, readonly: bool = False):
    host = cfg["imap_host"]
    port = int(cfg["imap_port"])
    user = cfg["imap_user"]
    password = cfg["imap_password"]
    folder = cfg.get("imap_folder") or "INBOX"
    try:
        imap = imaplib.IMAP4_SSL(host, port)
        imap.login(user, password)
    except OSError as exc:
        raise HybridChannelError("network", "IMAP connect failed", cause=exc) from exc
    status, _ = imap.select(folder, readonly=readonly)
    if status != "OK":
        try:
            imap.logout()
        except Exception:
            pass
        raise HybridChannelError("api", f"IMAP select failed: {folder}")
    return imap


def _process_unseen_messages(
    imap: Any,
    cfg: dict,
    *,
    pending: Dict[str, Dict[str, Any]],
    on_match,
) -> None:
    processed_folder = (cfg.get("imap_processed_folder") or "").strip()
    status, data = imap.search(None, "UNSEEN")
    if status != "OK" or not data or not data[0]:
        return
    for num in data[0].split():
        status, fetched = imap.fetch(num, "(RFC822)")
        if status != "OK" or not fetched or not fetched[0]:
            continue
        raw = fetched[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            continue
        msg = email.message_from_bytes(bytes(raw))
        body = _message_body_text(msg)
        if not body.strip():
            imap.store(num, "+FLAGS", "\\Seen")
            continue
        if _is_outbound_service_body(body):
            imap.store(num, "+FLAGS", "\\Seen")
            continue
        if not pending:
            continue
        matched = _match_task_id(pending, msg, body)
        if not matched:
            continue
        on_match(matched, body, num)
        imap.store(num, "+FLAGS", "\\Seen")
        if processed_folder:
            try:
                imap.copy(num, processed_folder)
            except imaplib.IMAP4.error:
                LOG.warning("flow_norm imap copy to %s failed", processed_folder)


def poll_balance_inbox(cfg: dict, state: Dict[str, Any]) -> None:
    balance_pending: Dict[str, Dict[str, Any]] = state.get("balance_pending") or {}
    if not balance_pending:
        return

    balance_responses: Dict[str, int] = state.setdefault("balance_responses", {})
    imap = None
    try:
        imap = _imap_connect_and_select(cfg, readonly=False)

        def on_match(tid: str, body: str, num: str) -> None:
            tokens = parse_balance_tokens_from_text(body)
            if tokens is None:
                LOG.warning("flow_norm balance reply unparsed task_id=%s", tid)
                return
            item = balance_pending.get(tid) or {}
            balance_responses[tid] = int(tokens)
            state.setdefault("inquiry_meta", {})[tid] = {
                "message_id": item.get("message_id") or "",
                "project_name": item.get("project_name") or "",
                "user_folder": item.get("user_folder") or "",
            }
            balance_pending.pop(tid, None)
            LOG.info("flow_norm balance response task_id=%s rub=%s", tid, tokens)

        _process_unseen_messages(imap, cfg, pending=balance_pending, on_match=on_match)
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def poll_inbox(cfg: dict, state: Dict[str, Any]) -> None:
    pending: Dict[str, Dict[str, Any]] = state.get("pending") or {}
    if not pending:
        return

    responses: Dict[str, str] = state.setdefault("responses", {})
    imap = None
    try:
        imap = _imap_connect_and_select(cfg, readonly=False)

        def on_match(tid: str, body: str, num: str) -> None:
            responses[tid] = body
            pending.pop(tid, None)
            LOG.info("flow_norm response task_id=%s chars=%s", tid, len(body))

        _process_unseen_messages(imap, cfg, pending=pending, on_match=on_match)
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass

def _match_chat_id(
    pending: Dict[str, Dict[str, Any]],
    msg: Message,
    body: str,
) -> Optional[str]:
    in_reply = _header_msg_ids(msg, "In-Reply-To")
    refs = _header_msg_ids(msg, "References")
    header_ids = in_reply | refs
    if header_ids:
        for cid, item in pending.items():
            mid = normalize_msg_id(str(item.get("message_id") or ""))
            if mid and mid in header_ids:
                return cid
            thread = normalize_msg_id(str(item.get("thread_message_id") or ""))
            if thread and thread in header_ids:
                return cid
    cid = extract_chat_id_from_text(body)
    if cid and cid in pending:
        return cid
    if FLOW_NORM_CHAT_TAG in body:
        for cid in pending:
            if cid in body:
                return cid
    return None


def poll_chat_inbox(cfg: dict, state: Dict[str, Any]) -> None:
    pending: Dict[str, Dict[str, Any]] = state.get("chat_pending") or {}
    if not pending:
        return
    responses: Dict[str, str] = state.setdefault("chat_responses", {})
    imap = None
    try:
        imap = _imap_connect_and_select(cfg, readonly=False)

        def on_match(cid: str, body: str, num: str) -> None:
            responses[cid] = body
            pending.pop(cid, None)
            LOG.info("flow_norm chat response chat_id=%s chars=%s", cid, len(body))

        status, data = imap.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return
        processed_folder = (cfg.get("imap_processed_folder") or "").strip()
        for num in data[0].split():
            status, fetched = imap.fetch(num, "(RFC822)")
            if status != "OK" or not fetched or not fetched[0]:
                continue
            raw = fetched[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(bytes(raw))
            body = _message_body_text(msg)
            if not body.strip():
                imap.store(num, "+FLAGS", "\Seen")
                continue
            if _is_outbound_service_body(body):
                imap.store(num, "+FLAGS", "\Seen")
                continue
            matched = _match_chat_id(pending, msg, body)
            if not matched:
                continue
            on_match(matched, body, num)
            imap.store(num, "+FLAGS", "\Seen")
            if processed_folder:
                try:
                    imap.copy(num, processed_folder)
                except imaplib.IMAP4.error:
                    LOG.warning("flow_norm imap copy chat failed")
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass

