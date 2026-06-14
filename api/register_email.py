"""SMTP для кодов регистрации на лендинге (отдельный ящик REGISTER_*)."""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any, Dict

from email_logistics.config import env_get
from email_logistics.smtp_send import _smtp_connect


def register_email_settings() -> Dict[str, Any]:
    return {
        "from": env_get("REGISTER_FROM") or env_get("REGISTER_SMTP_USER"),
        "from_name": env_get("REGISTER_FROM_NAME", "Sinlex"),
        "smtp_host": env_get("REGISTER_SMTP_HOST"),
        "smtp_port": int(env_get("REGISTER_SMTP_PORT", "465") or "465"),
        "smtp_user": env_get("REGISTER_SMTP_USER"),
        "smtp_password": env_get("REGISTER_SMTP_PASSWORD"),
        "smtp_tls": env_get("REGISTER_SMTP_TLS", "1").lower() in ("1", "true", "yes"),
    }


def require_register_email_settings() -> Dict[str, Any]:
    cfg = register_email_settings()
    missing = [k for k in ("from", "smtp_host", "smtp_user", "smtp_password") if not cfg.get(k)]
    if missing:
        raise RuntimeError(f"Register SMTP not configured: {', '.join(missing)}")
    return cfg


def send_register_code_email(email_to: str, code: str) -> None:
    cfg = require_register_email_settings()
    from_addr = cfg["from"]
    from_name = cfg.get("from_name") or "Sinlex"
    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    use_tls = bool(cfg.get("smtp_tls", True))

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = email_to
    msg["Subject"] = "Sinlex — код подтверждения регистрации"
    msg["Message-ID"] = make_msgid(domain="sinlex.tech")
    msg.set_content(
        "Здравствуйте!\n\n"
        "Ваш код для регистрации в Sinlex:\n\n"
        f"  {code}\n\n"
        "Код действует 15 минут.\n"
        "Если вы не запрашивали регистрацию — просто игнорируйте это письмо.\n\n"
        "— Команда Sinlex\n"
    )

    if use_tls and port == 465:
        server = _smtp_connect(host, port, timeout=60, use_ssl=True)
    else:
        server = _smtp_connect(host, port, timeout=60, use_ssl=False, starttls=use_tls)
    with server:
        if user and password:
            server.login(user, password)
        server.send_message(msg)
