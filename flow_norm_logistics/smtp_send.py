"""Исходящая отправка PDF для канала нормировки «Поток»."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Tuple

from email_logistics.smtp_send import _smtp_connect
from flow_norm_channel.markers import (
    build_balance_inquiry_body,
    build_chat_question_body,
    build_outbound_body,
)
from flow_drawing_io import drawing_mime_type, safe_drawing_filename
from hybrid_channel.errors import HybridChannelError

LOG = logging.getLogger("flow_norm_logistics.smtp")


def _attach_drawing(msg: EmailMessage, drawing_bytes: bytes, filename: str) -> None:
    fname = safe_drawing_filename(filename)
    maintype, subtype = drawing_mime_type(fname)
    msg.add_attachment(drawing_bytes, maintype=maintype, subtype=subtype, filename=fname)


def send_drawing_email(
    cfg: dict,
    *,
    pdf_bytes: bytes,
    project_name: str,
    task_id: str,
    user_folder: str = "",
) -> Tuple[str, str]:
    if not pdf_bytes:
        raise HybridChannelError("api", "Empty PDF payload")

    to_addr = cfg["to"]
    from_addr = cfg["from"]
    subject = f"[Sinlex Поток] Нормировка 2D — {(project_name or '—')[:120]}"
    body = build_outbound_body(project_name, task_id, user_folder=user_folder)
    message_id = make_msgid(domain="sinlex.local")

    msg = EmailMessage()
    msg["From"] = formataddr(("Sinlex Поток", from_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Reply-To"] = from_addr
    msg.set_content(body)
    _attach_drawing(msg, pdf_bytes, "drawing.pdf")

    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    use_tls = bool(cfg.get("smtp_tls", True))

    try:
        if use_tls and port == 465:
            server = _smtp_connect(host, port, timeout=120, use_ssl=True)
        else:
            server = _smtp_connect(
                host, port, timeout=120, use_ssl=False, starttls=use_tls
            )
        with server:
            if user and password:
                server.login(user, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        LOG.exception("flow_norm smtp send failed task_id=%s", task_id)
        raise HybridChannelError("network", "SMTP send failed", cause=exc) from exc

    LOG.info(
        "flow_norm sent task_id=%s project=%s message_id=%s bytes=%s",
        task_id,
        (project_name or "")[:80],
        message_id,
        len(pdf_bytes),
    )
    return message_id, subject


def send_balance_inquiry_email(
    cfg: dict,
    *,
    pdf_bytes: bytes,
    project_name: str,
    task_id: str,
    user_balance: int,
    user_email: str = "",
    user_folder: str = "",
) -> Tuple[str, str]:
    if not pdf_bytes:
        raise HybridChannelError("api", "Empty PDF payload")
    to_addr = cfg["to"]
    from_addr = cfg["from"]
    subject = f"[Sinlex Поток] Стоимость нормировки — {(project_name or '—')[:100]}"
    body = build_balance_inquiry_body(
        project_name,
        task_id,
        user_balance=int(user_balance),
        user_email=user_email,
        user_folder=user_folder,
    )
    message_id = make_msgid(domain="sinlex.local")

    msg = EmailMessage()
    msg["From"] = formataddr(("Sinlex Поток", from_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Reply-To"] = from_addr
    msg.set_content(body)
    _attach_drawing(msg, pdf_bytes, "drawing.pdf")

    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    use_tls = bool(cfg.get("smtp_tls", True))

    try:
        if use_tls and port == 465:
            server = _smtp_connect(host, port, timeout=120, use_ssl=True)
        else:
            server = _smtp_connect(
                host, port, timeout=120, use_ssl=False, starttls=use_tls
            )
        with server:
            if user and password:
                server.login(user, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        LOG.exception("flow_norm balance inquiry failed task_id=%s", task_id)
        raise HybridChannelError("network", "SMTP send failed", cause=exc) from exc

    LOG.info(
        "flow_norm balance inquiry task_id=%s balance=%s message_id=%s",
        task_id,
        user_balance,
        message_id,
    )
    return message_id, subject

def send_drawing_attachment_email(
    cfg: dict,
    *,
    drawing_bytes: bytes,
    drawing_filename: str,
    subject: str,
    body: str,
    reply_to_message_id: str = "",
) -> Tuple[str, str]:
    if not drawing_bytes:
        raise HybridChannelError("api", "Empty drawing payload")
    to_addr = cfg["to"]
    from_addr = cfg["from"]
    message_id = make_msgid(domain="sinlex.local")
    msg = EmailMessage()
    msg["From"] = formataddr(("Sinlex Поток", from_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Reply-To"] = from_addr
    if reply_to_message_id:
        mid = reply_to_message_id.strip()
        if not mid.startswith("<"):
            mid = f"<{mid}>"
        msg["In-Reply-To"] = mid
        msg["References"] = mid
    msg.set_content(body)
    _attach_drawing(msg, drawing_bytes, drawing_filename)
    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    use_tls = bool(cfg.get("smtp_tls", True))
    try:
        if use_tls and port == 465:
            server = _smtp_connect(host, port, timeout=120, use_ssl=True)
        else:
            server = _smtp_connect(host, port, timeout=120, use_ssl=False, starttls=use_tls)
        with server:
            if user and password:
                server.login(user, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        LOG.exception("flow_norm attachment send failed")
        raise HybridChannelError("network", "SMTP send failed", cause=exc) from exc
    return message_id, subject


def send_chat_question_email(
    cfg: dict,
    *,
    drawing_bytes: bytes,
    drawing_filename: str,
    project_name: str,
    task_id: str,
    chat_id: str,
    question: str,
    reply_to_message_id: str = "",
    user_folder: str = "",
) -> Tuple[str, str]:
    body = build_chat_question_body(
        project_name, task_id, chat_id, question, user_folder=user_folder
    )
    subject = f"[Sinlex Поток] Уточнение — {(project_name or '—')[:100]}"
    return send_drawing_attachment_email(
        cfg,
        drawing_bytes=drawing_bytes,
        drawing_filename=drawing_filename,
        subject=subject,
        body=body,
        reply_to_message_id=reply_to_message_id,
    )

