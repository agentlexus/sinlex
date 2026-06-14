"""Хранение заказов пользователя: /opt/sinlex/orders/<user_folder>/<order_id>/."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any

ORDERS_ROOT = "/opt/sinlex/orders"

ORDER_STAGES: list[tuple[str, str]] = [
    ("placed", "Размещение"),
    ("agreement", "Согласование"),
    ("payment", "Оплата"),
    ("production", "Производство"),
    ("shipping", "Отправка"),
    ("completed", "Завершён"),
]

STAGE_LABELS = dict(ORDER_STAGES)
DEFAULT_STAGE = "placed"


def orders_base_dir(user_folder: str) -> str:
    folder = (user_folder or "").strip()
    if not folder:
        raise ValueError("user_folder required")
    return os.path.join(ORDERS_ROOT, folder)


def _order_dir(user_folder: str, order_id: str) -> str:
    return os.path.join(orders_base_dir(user_folder), order_id)


def _order_json_path(user_folder: str, order_id: str) -> str:
    return os.path.join(_order_dir(user_folder, order_id), "order.json")


def _new_order_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage or "—")


def create_user_order(
    *,
    user_folder: str,
    user_email: str,
    project_name: str,
    payload: dict[str, Any],
    project_dir: str | None = None,
    pdf_path: str | None = None,
    step_path: str | None = None,
    pdf_bytes: bytes | None = None,
    step_bytes: bytes | None = None,
    step_filename: str = "model.stp",
    stage: str = DEFAULT_STAGE,
) -> dict[str, Any]:
    """Создать заказ в orders/<user>/<id>/ и скопировать вложения."""
    order_id = _new_order_id()
    order_dir = _order_dir(user_folder, order_id)
    os.makedirs(order_dir, exist_ok=True)
    requisites_dir = os.path.join(order_dir, "requisites")
    os.makedirs(requisites_dir, exist_ok=True)

    attachments: dict[str, str] = {}

    if pdf_bytes:
        pdf_name = "drawing.pdf"
        with open(os.path.join(order_dir, pdf_name), "wb") as f:
            f.write(pdf_bytes)
        attachments["pdf"] = pdf_name
    elif pdf_path and os.path.isfile(pdf_path):
        pdf_name = os.path.basename(pdf_path)
        shutil.copy2(pdf_path, os.path.join(order_dir, pdf_name))
        attachments["pdf"] = pdf_name

    if step_bytes:
        safe_step = os.path.basename(step_filename) or "model.stp"
        with open(os.path.join(order_dir, safe_step), "wb") as f:
            f.write(step_bytes)
        attachments["step"] = safe_step
    elif step_path and os.path.isfile(step_path):
        step_name = os.path.basename(step_path)
        shutil.copy2(step_path, os.path.join(order_dir, step_name))
        attachments["step"] = step_name

    now = datetime.now(timezone.utc).astimezone()
    record: dict[str, Any] = {
        "id": order_id,
        "created_at": now.isoformat(timespec="seconds"),
        "created_at_display": payload.get("Дата") or now.strftime("%d.%m.%Y %H:%M"),
        "stage": stage if stage in STAGE_LABELS else DEFAULT_STAGE,
        "user_email": user_email,
        "project_name": project_name,
        "project_dir": project_dir or "",
        "payload": dict(payload),
        "attachments": attachments,
        "requisites_files": [],
        "manager_email": "info@sinlex.ru",
    }
    save_order(user_folder, order_id, record)
    record["order_dir"] = order_dir
    return record


def save_order(user_folder: str, order_id: str, record: dict[str, Any]) -> str:
    path = _order_json_path(user_folder, order_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return path


def load_order(user_folder: str, order_id: str) -> dict[str, Any] | None:
    path = _order_json_path(user_folder, order_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("id", order_id)
    data["order_dir"] = _order_dir(user_folder, order_id)
    return data


def list_user_orders(user_folder: str) -> list[dict[str, Any]]:
    base = orders_base_dir(user_folder)
    if not os.path.isdir(base):
        return []
    out: list[dict[str, Any]] = []
    for name in os.listdir(base):
        order = load_order(user_folder, name)
        if order:
            out.append(order)
    out.sort(key=lambda o: o.get("created_at") or "", reverse=True)
    return out


def add_requisites_files(
    user_folder: str,
    order_id: str,
    files: list[tuple[str, bytes]],
) -> list[str]:
    order = load_order(user_folder, order_id)
    if not order:
        raise FileNotFoundError("order not found")
    req_dir = os.path.join(_order_dir(user_folder, order_id), "requisites")
    os.makedirs(req_dir, exist_ok=True)
    saved: list[str] = order.get("requisites_files") or []
    for fname, data in files:
        safe = os.path.basename(fname).replace("..", "_")
        if not safe:
            continue
        path = os.path.join(req_dir, safe)
        with open(path, "wb") as f:
            f.write(data)
        if safe not in saved:
            saved.append(safe)
    order["requisites_files"] = saved
    save_order(user_folder, order_id, order)
    return saved

def delete_user_order(user_folder: str, order_id: str) -> bool:
    """Удалить папку заказа orders/<user>/<order_id>/ целиком."""
    oid = (order_id or "").strip()
    if not oid or "/" in oid or "\\" in oid or ".." in oid:
        raise ValueError("invalid order_id")
    order_dir = _order_dir(user_folder, oid)
    base = os.path.realpath(orders_base_dir(user_folder))
    real = os.path.realpath(order_dir)
    if not (real == base or real.startswith(base + os.sep)):
        raise ValueError("invalid path")
    if not os.path.isdir(real):
        return False
    shutil.rmtree(real)
    return True
