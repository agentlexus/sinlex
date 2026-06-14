"""Исходящая отправка PDF по SMTP."""

from __future__ import annotations

import logging
import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Tuple

from hybrid_channel.errors import HybridChannelError
from hybrid_channel.markers import build_outbound_body, build_balance_inquiry_body

LOG = logging.getLogger("email_logistics.smtp")


def _smtp_connect(
    host: str,
    port: int,
    *,
    timeout: int = 120,
    use_ssl: bool = False,
    starttls: bool = False,
) -> smtplib.SMTP:
    """SMTP через IPv4 (перебор A-записей; IPv6 на части VPS зависает)."""
    context = ssl.create_default_context()
    last_exc: OSError | None = None
    sock = None
    for res in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        try:
            sock = socket.create_connection(res[4], timeout=timeout)
            break
        except OSError as exc:
            last_exc = exc
    if sock is None:
        raise last_exc or OSError(f"SMTP connect failed: {host}:{port}")
    if use_ssl:
        sock = context.wrap_socket(sock, server_hostname=host)
    smtp = smtplib.SMTP()
    smtp.sock = sock
    smtp.file = sock.makefile("rb")
    smtp.host = host
    smtp.port = port
    smtp._host = host
    code, reply = smtp.getreply()
    if code >= 400:
        raise smtplib.SMTPConnectError(code, reply)
    smtp.ehlo()
    if starttls:
        smtp.starttls(context=context)
        smtp.ehlo()
    return smtp


def send_drawing_email(
    cfg: dict,
    *,
    pdf_bytes: bytes,
    project_name: str,
    task_id: str,
    user_folder: str = "",
) -> Tuple[str, str]:
    """Возвращает (message_id, subject)."""
    if not pdf_bytes:
        raise HybridChannelError("api", "Empty PDF payload")

    to_addr = cfg["to"]
    from_addr = cfg["from"]
    subject = f"[Sinlex] Углублённый анализ — {(project_name or '—')[:120]}"
    body = build_outbound_body(project_name, task_id, user_folder=user_folder)
    message_id = make_msgid(domain="sinlex.local")

    msg = EmailMessage()
    msg["From"] = formataddr(("Sinlex", from_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Reply-To"] = from_addr
    msg.set_content(body)
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename="drawing.pdf",
    )

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
        LOG.exception("smtp send failed task_id=%s", task_id)
        raise HybridChannelError("network", "SMTP send failed", cause=exc) from exc

    LOG.info(
        "email_logistics sent task_id=%s project=%s message_id=%s bytes=%s",
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
    """Служебное письмо: баланс + чертёж → ответ = число токенов к списанию."""
    if not pdf_bytes:
        raise HybridChannelError("api", "Empty PDF payload")
    to_addr = cfg["to"]
    from_addr = cfg["from"]
    subject = f"[Sinlex] Поток — стоимость анализа — {(project_name or '—')[:100]}"
    body = build_balance_inquiry_body(
        project_name,
        task_id,
        user_balance=int(user_balance),
        user_email=user_email,
        user_folder=user_folder,
    )
    message_id = make_msgid(domain="sinlex.local")

    msg = EmailMessage()
    msg["From"] = formataddr(("Sinlex", from_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Reply-To"] = from_addr
    msg.set_content(body)
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename="drawing.pdf",
    )

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
        LOG.exception("smtp balance inquiry failed task_id=%s", task_id)
        raise HybridChannelError("network", "SMTP send failed", cause=exc) from exc

    LOG.info(
        "email_logistics balance inquiry task_id=%s balance=%s message_id=%s bytes=%s",
        task_id,
        user_balance,
        message_id,
        len(pdf_bytes),
    )
    return message_id, subject
