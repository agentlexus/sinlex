"""Размещение производственного заказа: JSON, email, Google Sheets."""
from __future__ import annotations

import sys
from pathlib import Path

_PAGE_MODULES = Path(__file__).resolve().parent / "page_modules"
if str(_PAGE_MODULES) not in sys.path:
    sys.path.insert(0, str(_PAGE_MODULES))

import json
import logging
import os
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any

import requests

from email_logistics.config import email_settings, env_get
from email_logistics.smtp_send import _smtp_connect
from payment import load_accounts
from project_store import projects_base_dir
from orders_store import create_user_order

LOG = logging.getLogger("order_placement")

ORDER_JSON_NAME = "order_placement.json"
GOOGLE_SCRIPT_URL = env_get(
    "ORDER_GOOGLE_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycbyXFAeCiAhUXzSRpARAYl4fN_8PRO5jgem4h_IVa6n7bS47jeRiuKU80R7hxRJ3PUKedQ/exec",
)
ORDER_EMAIL_TO = env_get("ORDER_EMAIL_TO", "info@sinlex.ru")


def _smtp_candidates() -> list[dict[str, Any]]:
    """Цепочка SMTP: ORDER_* → SUFFLER (mail.ru) → REGISTER (nic.ru).

    nic.ru обрывает соединение при нескольких крупных вложениях; mail.ru — нет.
    """
    out: list[dict[str, Any]] = []

    def _add(
        label: str,
        *,
        from_addr: str,
        from_name: str,
        host: str,
        port: int,
        user: str,
        password: str,
        use_tls: bool,
    ) -> None:
        if not all([from_addr, host, user, password]):
            return
        out.append(
            {
                "label": label,
                "from": from_addr,
                "from_name": from_name,
                "smtp_host": host,
                "smtp_port": int(port),
                "smtp_user": user,
                "smtp_password": password,
                "smtp_tls": use_tls,
            }
        )

    if env_get("ORDER_SMTP_HOST") and env_get("ORDER_SMTP_USER"):
        _add(
            "ORDER",
            from_addr=env_get("ORDER_SMTP_FROM") or env_get("ORDER_SMTP_USER"),
            from_name=env_get("ORDER_SMTP_FROM_NAME", "Sinlex"),
            host=env_get("ORDER_SMTP_HOST"),
            port=int(env_get("ORDER_SMTP_PORT", "465") or "465"),
            user=env_get("ORDER_SMTP_USER"),
            password=env_get("ORDER_SMTP_PASSWORD"),
            use_tls=env_get("ORDER_SMTP_TLS", "1").lower() in ("1", "true", "yes"),
        )

    suffler = email_settings()
    _add(
        "SUFFLER",
        from_addr=suffler.get("from") or suffler.get("smtp_user") or "",
        from_name=env_get("ORDER_SMTP_FROM_NAME", "Sinlex"),
        host=suffler.get("smtp_host") or "",
        port=int(suffler.get("smtp_port") or 2525),
        user=suffler.get("smtp_user") or "",
        password=suffler.get("smtp_password") or "",
        use_tls=bool(suffler.get("smtp_tls", True)),
    )

    _add(
        "REGISTER",
        from_addr=env_get("REGISTER_FROM") or env_get("REGISTER_SMTP_USER"),
        from_name=env_get("REGISTER_FROM_NAME", "Sinlex"),
        host=env_get("REGISTER_SMTP_HOST"),
        port=int(env_get("REGISTER_SMTP_PORT", "465") or "465"),
        user=env_get("REGISTER_SMTP_USER"),
        password=env_get("REGISTER_SMTP_PASSWORD"),
        use_tls=env_get("REGISTER_SMTP_TLS", "1").lower() in ("1", "true", "yes"),
    )

    # dedupe by host:user
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for cfg in out:
        key = f"{cfg['smtp_host']}:{cfg['smtp_user']}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(cfg)
    return unique


def _user_contact(email: str) -> dict[str, str]:
    acc = load_accounts().get(email) or {}
    first = (acc.get("first_name") or "").strip()
    last = (acc.get("last_name") or "").strip()
    contact = f"{first} {last}".strip()
    if not contact:
        contact = (acc.get("company_name") or "").strip()
    return {
        "Контакт": contact,
        "Телефон": (acc.get("phone") or "").strip(),
        "Email": email,
        "email": email,
    }


def _resolve_step_path(project_dir: str, project_name: str) -> str | None:
    from upload_step import safe_dir_name

    safe = safe_dir_name(project_name)
    for name in (f"{safe}.stp", f"{safe}.step", f"{safe}.STP"):
        path = os.path.join(project_dir, name)
        if os.path.isfile(path):
            return path
    if os.path.isdir(project_dir):
        for fname in sorted(os.listdir(project_dir)):
            low = fname.lower()
            if low.endswith(".stp") or low.endswith(".step"):
                return os.path.join(project_dir, fname)
    return None


def _resolve_pdf_path(project_dir: str, project_name: str) -> str | None:
    from upload_step import safe_dir_name

    safe = safe_dir_name(project_name)
    canonical = os.path.join(project_dir, f"{safe}.pdf")
    if os.path.isfile(canonical):
        return canonical
    if os.path.isdir(project_dir):
        for fname in sorted(os.listdir(project_dir)):
            if fname.lower().endswith(".pdf"):
                return os.path.join(project_dir, fname)
    return None


def build_order_payload(
    *,
    project_name: str,
    user_folder: str,
    user_email: str,
    material: str,
    dimensions_text: str,
    batch_size: int,
    unit_price: int,
    total_price: int,
    comment: str = "",
) -> dict[str, Any]:
    payload = {
        "Дата": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "Проект": project_name,
        "Материал": material,
        "Габариты": dimensions_text,
        "Партия": batch_size,
        "Цена за ед.": int(unit_price),
        "Общая стоимость": int(total_price),
        "Комментарий": (comment or "").strip(),
    }
    payload.update(_user_contact(user_email))
    return payload


def save_order_json(project_dir: str, payload: dict[str, Any]) -> str:
    os.makedirs(project_dir, exist_ok=True)
    path = os.path.join(project_dir, ORDER_JSON_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def _build_order_email_message(
    *,
    payload: dict[str, Any],
    project_name: str,
    from_addr: str,
    from_name: str,
    pdf_path: str | None,
    step_path: str | None,
    pdf_bytes: bytes | None,
    step_bytes: bytes | None,
    pdf_filename: str,
    step_filename: str,
    attach_pdf: bool,
    attach_step: bool,
) -> EmailMessage:
    if not pdf_bytes and pdf_path and os.path.isfile(pdf_path):
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        pdf_filename = os.path.basename(pdf_path)
    if not step_bytes and step_path and os.path.isfile(step_path):
        with open(step_path, "rb") as f:
            step_bytes = f.read()
        step_filename = os.path.basename(step_path)

    attach_names: list[str] = []
    if attach_pdf and pdf_bytes:
        attach_names.append(f"чертёж ({pdf_filename})")
    if attach_step and step_bytes:
        attach_names.append(f"STEP ({step_filename})")

    lines = [f"{k}: {v}" for k, v in payload.items()]
    body = (
        "Новый заказ на производство из Sinlex.\n\n"
        + "\n".join(lines)
        + "\n\nВложения: "
        + (", ".join(attach_names) if attach_names else "нет")
        + "\n"
    )

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = ORDER_EMAIL_TO
    msg["Subject"] = f"[Sinlex] Размещение заказа — {(project_name or '—')[:120]}"
    msg["Message-ID"] = make_msgid(domain="sinlex.tech")
    msg["Reply-To"] = payload.get("Email") or from_addr
    msg.set_content(body)

    if attach_pdf and pdf_bytes:
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=pdf_filename,
        )
    if attach_step and step_bytes:
        msg.add_attachment(
            step_bytes,
            maintype="application",
            subtype="octet-stream",
            filename=step_filename,
        )
    return msg


def _smtp_send_message(cfg: dict[str, Any], msg: EmailMessage) -> None:
    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    use_tls = bool(cfg.get("smtp_tls", True))
    if use_tls and port == 465:
        server = _smtp_connect(host, port, timeout=120, use_ssl=True)
    else:
        server = _smtp_connect(host, port, timeout=120, use_ssl=False, starttls=use_tls)
    with server:
        if user and password:
            server.login(user, password)
        server.send_message(msg)


def send_order_email(
    *,
    payload: dict[str, Any],
    project_name: str,
    pdf_path: str | None,
    step_path: str | None,
    pdf_bytes: bytes | None = None,
    step_bytes: bytes | None = None,
    pdf_filename: str = "drawing.pdf",
    step_filename: str = "model.stp",
) -> None:
    candidates = _smtp_candidates()
    if not candidates:
        raise RuntimeError("SMTP не настроен (ORDER_*, SUFFLER_* или REGISTER_*)")

    plans = [
        ("оба файла", True, True),
        ("только STEP", False, True),
        ("только чертёж", True, False),
        ("без вложений", False, False),
    ]
    last_exc: Exception | None = None

    for plan_label, attach_pdf, attach_step in plans:
        if not attach_pdf and not attach_step and plan_label != "без вложений":
            continue
        if attach_pdf and not (pdf_path or pdf_bytes):
            continue
        if attach_step and not (step_path or step_bytes):
            continue

        for cfg in candidates:
            from_addr = cfg["from"]
            from_name = cfg.get("from_name") or "Sinlex"
            msg = _build_order_email_message(
                payload=payload,
                project_name=project_name,
                from_addr=from_addr,
                from_name=from_name,
                pdf_path=pdf_path,
                step_path=step_path,
                pdf_bytes=pdf_bytes,
                step_bytes=step_bytes,
                pdf_filename=pdf_filename,
                step_filename=step_filename,
                attach_pdf=attach_pdf,
                attach_step=attach_step,
            )
            try:
                _smtp_send_message(cfg, msg)
                LOG.info(
                    "order email sent project=%s to=%s via=%s plan=%s",
                    project_name,
                    ORDER_EMAIL_TO,
                    cfg.get("label"),
                    plan_label,
                )
                return
            except Exception as exc:
                last_exc = exc
                LOG.warning(
                    "order email attempt failed via=%s plan=%s: %s",
                    cfg.get("label"),
                    plan_label,
                    exc,
                )

    raise RuntimeError(f"Не удалось отправить письмо: {last_exc}")


_GOOGLE_SHEET_COLUMNS = [
    "Дата",
    "Проект",
    "Материал",
    "Габариты",
    "Партия",
    "Цена за ед.",
    "Общая стоимость",
    "Контакт",
    "Телефон",
    "Email",
    "Комментарий",
]


def _sheet_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _google_sheet_body(payload: dict[str, Any]) -> dict[str, Any]:
    """Тело для Apps Script: row + русские/английские алиасы под разные скрипты."""
    project = _sheet_cell(payload.get("Проект"))
    material = _sheet_cell(payload.get("Материал"))
    dimensions = _sheet_cell(payload.get("Габариты"))
    batch = payload.get("Партия", "")
    unit_price = payload.get("Цена за ед.", "")
    total = payload.get("Общая стоимость", "")
    contact = _sheet_cell(payload.get("Контакт"))
    phone = _sheet_cell(payload.get("Телефон"))
    email = _sheet_cell(
        payload.get("Email") or payload.get("email") or payload.get("user_email")
    )
    comment = _sheet_cell(payload.get("Комментарий"))
    date = _sheet_cell(payload.get("Дата"))

    row = [
        date,
        project,
        material,
        dimensions,
        batch,
        unit_price,
        total,
        contact,
        phone,
        email,
        comment,
    ]

    return {
        **payload,
        "row": row,
        "values": row,
        "data": row,
        # дата
        "date": date,
        "timestamp": date,
        "Дата": date,
        # проект
        "project": project,
        "projectName": project,
        "project_name": project,
        "name": project,
        "title": project,
        "nazvanie": project,
        "naimenovanie": project,
        "Название проекта": project,
        "название проекта": project,
        "Проект": project,
        # материал / габариты / партия
        "material": material,
        "Материал": material,
        "dimensions": dimensions,
        "gabarites": dimensions,
        "size": dimensions,
        "Габариты": dimensions,
        "quantity": batch,
        "batch": batch,
        "party": batch,
        "qty": batch,
        "count": batch,
        "Партия": batch,
        # цена за ед.
        "unit_price": unit_price,
        "unitPrice": unit_price,
        "pricePerUnit": unit_price,
        "price_item": unit_price,
        "price_unit": unit_price,
        "item_price": unit_price,
        "cost_per_unit": unit_price,
        "unit_cost": unit_price,
        "cena": unit_price,
        "cena_za_ed": unit_price,
        "stoimost_ed": unit_price,
        "Цена за ед.": unit_price,
        "Цена": unit_price,
        # общая стоимость
        "total": total,
        "totalPrice": total,
        "total_price": total,
        "total_cost": total,
        "sum": total,
        "stoimost": total,
        "Общая стоимость": total,
        # контакт
        "contact": contact,
        "contact_name": contact,
        "contactName": contact,
        "full_name": contact,
        "fullName": contact,
        "fio": contact,
        "client": contact,
        "kontakt": contact,
        "Контакт": contact,
        "ФИО": contact,
        # телефон / email
        "phone": phone,
        "phone_number": phone,
        "phoneNumber": phone,
        "tel": phone,
        "telefon": phone,
        "Телефон": phone,
        "email": email,
        "user_email": email,
        "userEmail": email,
        "client_email": email,
        "clientEmail": email,
        "customer_email": email,
        "mail": email,
        "e_mail": email,
        "E-mail": email,
        "e-mail": email,
        "EMail": email,
        "Email": email,
        "Почта": email,
        "Имейл": email,
        # комментарий
        "comment": comment,
        "Комментарий": comment,
    }


_GOOGLE_SHEET_AUTH_HINT = (
    "Доступ к веб-приложению Google закрыт (HTTP 401). "
    "В Apps Script: Развернуть → Новое развертывание → Веб-приложение → "
    "«Имеют доступ»: Все (Anyone). См. scripts/order_placement_gas.js"
)


def submit_to_google_sheet(payload: dict[str, Any]) -> None:
    if not GOOGLE_SCRIPT_URL:
        raise RuntimeError("ORDER_GOOGLE_SCRIPT_URL не задан")

    body = _google_sheet_body(payload)
    # Сначала row (все 11 колонок), затем полный объект с алиасами
    attempts = [{"row": body["row"]}, body]
    last_text = ""
    last_status = 0
    for attempt in attempts:
        resp = requests.post(
            GOOGLE_SCRIPT_URL,
            json=attempt,
            headers={"Content-Type": "application/json"},
            timeout=45,
            allow_redirects=True,
        )
        last_status = resp.status_code
        last_text = (resp.text or "")[:300]
        if resp.status_code < 400 and "accounts.google.com" not in last_text.lower():
            if "success" in last_text.lower() or '"ok"' in last_text.lower():
                return
    if last_status == 401 or "accounts.google.com" in last_text.lower():
        raise RuntimeError(_GOOGLE_SHEET_AUTH_HINT)
    if last_status >= 400:
        raise RuntimeError(f"Google Sheets: HTTP {last_status}: {last_text}")
    raise RuntimeError(f"Google Sheets: неожиданный ответ: {last_text}")


def place_manufacturing_order(
    *,
    project_name: str,
    user_folder: str,
    user_email: str,
    material: str,
    dimensions_text: str,
    batch_size: int,
    unit_price: int,
    total_price: int,
    comment: str = "",
    pdf_path: str | None = None,
    step_path: str | None = None,
    pdf_bytes: bytes | None = None,
    step_bytes: bytes | None = None,
    step_filename: str = "model.stp",
    project_dir: str | None = None,
) -> dict[str, Any]:
    """Сохранить JSON, отправить email и строку в Google Таблицу."""
    if not user_email:
        raise RuntimeError("Требуется вход в аккаунт")
    if not project_name:
        raise RuntimeError("Не указан проект")

    from upload_step import safe_dir_name

    if not project_dir:
        project_dir = os.path.join(
            projects_base_dir(user_folder), safe_dir_name(project_name)
        )

    if not pdf_path:
        pdf_path = _resolve_pdf_path(project_dir, project_name)
    if not step_path:
        step_path = _resolve_step_path(project_dir, project_name)

    payload = build_order_payload(
        project_name=project_name,
        user_folder=user_folder,
        user_email=user_email,
        material=material,
        dimensions_text=dimensions_text,
        batch_size=batch_size,
        unit_price=unit_price,
        total_price=total_price,
        comment=comment,
    )

    json_path = save_order_json(project_dir, payload)
    errors: list[str] = []
    user_order: dict[str, Any] | None = None

    try:
        user_order = create_user_order(
            user_folder=user_folder,
            user_email=user_email,
            project_name=project_name,
            payload=payload,
            project_dir=project_dir,
            pdf_path=pdf_path,
            step_path=step_path,
            pdf_bytes=pdf_bytes,
            step_bytes=step_bytes,
            step_filename=step_filename,
        )
    except Exception as exc:
        LOG.exception("user order store failed")
        errors.append(f"Мои заказы: {exc}")

    try:
        send_order_email(
            payload=payload,
            project_name=project_name,
            pdf_path=pdf_path,
            step_path=step_path,
            pdf_bytes=pdf_bytes,
            step_bytes=step_bytes,
            step_filename=step_filename,
        )
        email_ok = True
    except Exception as exc:
        LOG.exception("order email failed")
        email_ok = False
        errors.append(f"Почта: {exc}")

    try:
        submit_to_google_sheet(payload)
        sheet_ok = True
    except Exception as exc:
        LOG.exception("google sheet failed")
        sheet_ok = False
        errors.append(f"Таблица: {exc}")

    return {
        "json_path": json_path,
        "email_ok": email_ok,
        "sheet_ok": sheet_ok,
        "payload": payload,
        "errors": errors,
        "order_id": (user_order or {}).get("id"),
        "order_dir": (user_order or {}).get("order_dir"),
    }
