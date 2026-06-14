"""Интеграция ЮKassa: создание платежей, webhook, активация тарифов."""
from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
PAYMENTS_FILE = os.path.join(BASE_DIR, "data", "payments.json")
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")
USER_PAYMENTS_DIR = os.path.join(BASE_DIR, "data", "user_payments")

TRIAL_TARIFF_ID = "trial"
TRIAL_PERIOD_DAYS = 10
TRIAL_PROJECT_LIMIT = 5

TARIFF_PLANS: dict[str, dict[str, Any]] = {
    "start": {
        "name": "Старт",
        "amount": 15000,
        "description": "Тариф Старт — Sinlex (1 мес.)",
        "features": [
            "До 10 проектов в месяц",
            "Базовый анализ чертежей",
            "Поддержка по email",
            "1 пользователь",
        ],
    },
    "basic": {
        "name": "Базовый",
        "amount": 40000,
        "description": "Тариф Базовый — Sinlex (1 мес.)",
        "features": [
            "До 30 проектов в месяц",
            "Расширенный анализ",
            "Приоритетная поддержка",
            "До 5 пользователей",
        ],
    },
    TRIAL_TARIFF_ID: {
        "name": "Пробный период",
        "amount": 0,
        "description": "Пробный доступ Sinlex (10 дней)",
        "features": [
            "До 5 проектов на расчёт",
            "10 дней с момента регистрации",
            "Базовый анализ STEP",
        ],
    },
    "enterprise": {
        "name": "Предприятие",
        "amount": 60000,
        "description": "Тариф Предприятие — Sinlex (1 мес.)",
        "features": [
            "Безлимитные проекты",
            "Полный функционал",
            "Персональный менеджер",
            "API и интеграции",
        ],
    },
}

TARIFF_PERIOD_DAYS = 30
TARIFF_PROJECT_LIMITS: dict[str, int | None] = {
    TRIAL_TARIFF_ID: TRIAL_PROJECT_LIMIT,
    "start": 10,
    "basic": 30,
    "enterprise": None,
}

PROJECTS_ROOT = os.path.join(BASE_DIR, "projects")
CASTING_ROOT = os.path.join(BASE_DIR, "casting")

def _effective_project_limit(profile: dict, tariff_id: str | None) -> int | None:
    """Лимит проектов: тариф + бонус project_limit_extra."""
    if not isinstance(profile, dict):
        profile = {}
    ov = profile.get("project_limit_override")
    if ov is not None:
        try:
            return int(ov)
        except (TypeError, ValueError):
            pass
    base = TARIFF_PROJECT_LIMITS.get(tariff_id) if tariff_id else profile.get("project_limit")
    extra = int(profile.get("project_limit_extra") or 0)
    if base is None:
        return None
    return int(base) + max(0, extra)



FLOW_TOPUP_MIN_AMOUNT = 5000
FLOW_RUB_PER_TOKEN = 10  # legacy: токен→руб при миграции
FLOW_BALANCE_RUB_KEY = "flow_balance_rub"
FLOW_STORAGE_RUB_MIGRATION_FLAG = "flow_balance_storage_rub_v1"
PURPOSE_TARIFF = "tariff"
PURPOSE_FLOW_TOKENS = "flow_tokens"

FLOW_PENDING_DIR = os.path.join(BASE_DIR, "data", "flow_pending")
FLOW_MAX_TOKENS_CHARGE = 500


def flow_rub_to_tokens(amount_rub: int) -> int:
    """Сколько токенов зачислить за оплату в рублях."""
    amount_rub = int(amount_rub)
    if amount_rub <= 0:
        return 0
    return amount_rub // FLOW_RUB_PER_TOKEN


def flow_tokens_rub_equiv(tokens: int) -> int:
    """Эквивалент баланса в рублях для подсказок UI."""
    return int(tokens) * FLOW_RUB_PER_TOKEN


def flow_topup_min_tokens() -> int:
    return flow_rub_to_tokens(FLOW_TOPUP_MIN_AMOUNT)

FLOW_TOKENS_LEGACY_MIGRATION_FLAG = "flow_tokens_migrated_from_1rub_v1"
FLOW_TOKENS_RATE_100_TO_10_FLAG = "flow_tokens_migrated_100rub_to_10rub_v1"
FLOW_RUB_PER_TOKEN_PREV = 100


def _migrate_flow_tokens_100_to_10_file(path: str, *, dry_run: bool = False) -> dict:
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    if not isinstance(profile, dict):
        profile = {}
    em = (profile.get("user_email") or "").strip()
    file_name = os.path.basename(path)
    if profile.get(FLOW_TOKENS_RATE_100_TO_10_FLAG):
        try:
            bal = max(0, int(profile.get("flow_tokens", 0)))
        except (TypeError, ValueError):
            bal = 0
        return {
            "file": file_name,
            "user_email": em,
            "skipped": True,
            "reason": "already_migrated_100_to_10",
            "balance": bal,
        }
    try:
        old_balance = max(0, int(profile.get("flow_tokens", 0)))
    except (TypeError, ValueError):
        old_balance = 0
    factor = FLOW_RUB_PER_TOKEN_PREV // FLOW_RUB_PER_TOKEN
    new_balance = old_balance * factor
    entry: dict = {
        "file": file_name,
        "user_email": em,
        "balance_before": old_balance,
        "balance_after": new_balance,
        "dry_run": dry_run,
    }
    if dry_run:
        return entry
    if old_balance != new_balance:
        profile.setdefault("transactions", []).append(
            {
                "date": _now_iso(),
                "type": "migration",
                "amount": new_balance - old_balance,
                "source": "rate_100rub_to_10rub",
                "payment_id": FLOW_TOKENS_RATE_100_TO_10_FLAG,
                "purpose": PURPOSE_FLOW_TOKENS,
                "balance_before": old_balance,
                "balance_after": new_balance,
                "note": f"Курс: 1 токен = {FLOW_RUB_PER_TOKEN} ₽ (было {FLOW_RUB_PER_TOKEN_PREV} ₽)",
            }
        )
    profile["flow_tokens"] = new_balance
    profile[FLOW_TOKENS_RATE_100_TO_10_FLAG] = True
    profile["flow_tokens_rate_migration_at"] = _now_iso()
    profile["updated_at"] = _now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    entry["migrated"] = True
    return entry


def migrate_flow_tokens_100rub_to_10rub(
    user_email: str | None = None,
    *,
    dry_run: bool = False,
) -> list[dict]:
    """Пересчитать балансы с курса 1 токен=100 ₽ на 1 токен=10 ₽ (×10)."""
    results: list[dict] = []
    if not os.path.isdir(USER_PAYMENTS_DIR):
        return results
    paths: list[str] = []
    if user_email:
        path = _user_payment_file(user_email.strip())
        if path and os.path.isfile(path):
            paths = [path]
    else:
        for name in sorted(os.listdir(USER_PAYMENTS_DIR)):
            if name.endswith(".json"):
                paths.append(os.path.join(USER_PAYMENTS_DIR, name))
    for path in paths:
        results.append(_migrate_flow_tokens_100_to_10_file(path, dry_run=dry_run))
    return results



def _migrate_flow_tokens_profile_file(path: str, *, dry_run: bool = False) -> dict:
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    if not isinstance(profile, dict):
        profile = {}
    em = (profile.get("user_email") or "").strip()
    file_name = os.path.basename(path)
    if profile.get(FLOW_TOKENS_LEGACY_MIGRATION_FLAG):
        try:
            bal = max(0, int(profile.get("flow_tokens", 0)))
        except (TypeError, ValueError):
            bal = 0
        return {
            "file": file_name,
            "user_email": em,
            "skipped": True,
            "reason": "already_migrated",
            "balance": bal,
        }
    try:
        old_balance = max(0, int(profile.get("flow_tokens", 0)))
    except (TypeError, ValueError):
        old_balance = 0
    new_balance = flow_rub_to_tokens(old_balance)
    entry: dict = {
        "file": file_name,
        "user_email": em,
        "balance_before": old_balance,
        "balance_after": new_balance,
        "dry_run": dry_run,
    }
    if dry_run:
        return entry
    if old_balance != new_balance:
        profile.setdefault("transactions", []).append(
            {
                "date": _now_iso(),
                "type": "migration",
                "amount": new_balance - old_balance,
                "source": "rate_1rub_to_100rub",
                "payment_id": "flow_tokens_migrated_from_1rub_v1",
                "purpose": PURPOSE_FLOW_TOKENS,
                "balance_before": old_balance,
                "balance_after": new_balance,
                "note": f"Курс: 1 токен = {FLOW_RUB_PER_TOKEN} ₽ (было 1:1)",
            }
        )
    profile["flow_tokens"] = new_balance
    profile[FLOW_TOKENS_LEGACY_MIGRATION_FLAG] = True
    profile["flow_tokens_migration_at"] = _now_iso()
    profile["updated_at"] = _now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    entry["migrated"] = True
    return entry


def migrate_flow_tokens_legacy_balances(
    user_email: str | None = None,
    *,
    dry_run: bool = False,
) -> list[dict]:
    """Пересчитать балансы с курса 1 токен=1 ₽ на 1 токен=100 ₽ (÷100, вниз).

    Идемпотентно: повторный вызов пропускает уже помеченные профили.
    """
    results: list[dict] = []
    if not os.path.isdir(USER_PAYMENTS_DIR):
        return results
    paths: list[str] = []
    if user_email:
        path = _user_payment_file(user_email.strip())
        if path and os.path.isfile(path):
            paths = [path]
        else:
            em = user_email.strip().lower()
            for name in os.listdir(USER_PAYMENTS_DIR):
                if not name.endswith(".json"):
                    continue
                pth = os.path.join(USER_PAYMENTS_DIR, name)
                try:
                    with open(pth, encoding="utf-8") as f:
                        prof = json.load(f)
                except Exception:
                    continue
                if (prof.get("user_email") or "").strip().lower() == em:
                    paths.append(pth)
    else:
        for name in sorted(os.listdir(USER_PAYMENTS_DIR)):
            if name.endswith(".json"):
                paths.append(os.path.join(USER_PAYMENTS_DIR, name))
    for path in paths:
        results.append(_migrate_flow_tokens_profile_file(path, dry_run=dry_run))
    return results




def migrate_flow_storage_to_rub(*, dry_run: bool = False) -> list[dict]:
    """Перенести flow_tokens → flow_balance_rub (×FLOW_RUB_PER_TOKEN), идемпотентно."""
    results: list[dict] = []
    if not os.path.isdir(USER_PAYMENTS_DIR):
        return results
    for name in sorted(os.listdir(USER_PAYMENTS_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(USER_PAYMENTS_DIR, name)
        try:
            with open(path, encoding="utf-8") as f:
                profile = json.load(f)
        except Exception:
            continue
        if not isinstance(profile, dict):
            continue
        em = (profile.get("user_email") or "").strip()
        if profile.get(FLOW_STORAGE_RUB_MIGRATION_FLAG):
            results.append({"file": name, "user_email": em, "skipped": True})
            continue
        before = _profile_flow_balance_rub(profile)
        entry = {
            "file": name,
            "user_email": em,
            "balance_rub_before": before,
            "balance_rub_after": before,
            "dry_run": dry_run,
        }
        if dry_run:
            results.append(entry)
            continue
        _set_profile_flow_balance_rub(profile, before)
        profile[FLOW_STORAGE_RUB_MIGRATION_FLAG] = True
        profile["flow_balance_storage_migrated_at"] = _now_iso()
        profile["updated_at"] = _now_iso()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        entry["migrated"] = True
        results.append(entry)
    return results


def normalize_project_key(project_name: str) -> str:
    """Ключ слота проекта (совпадает с именем папки на диске)."""
    return (project_name or "").strip().replace(" ", "_").replace("/", "_")


def load_env() -> None:
    """Загрузить переменные из /opt/sinlex/.env (не перезаписывает уже заданные)."""
    if not os.path.isfile(ENV_FILE):
        return
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


load_env()

_SHOP_ID = os.environ.get("YOOKASSA_SHOP_ID", "").strip()
_SECRET_KEY = os.environ.get("YOOKASSA_SECRET_KEY", "").strip()
_CONFIGURED = False


def _ensure_yookassa() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    if not _SHOP_ID or not _SECRET_KEY:
        raise RuntimeError("YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY должны быть в .env")
    from yookassa import Configuration

    Configuration.configure(_SHOP_ID, _SECRET_KEY)
    _CONFIGURED = True


def public_app_url() -> str:
    return os.environ.get("SINLEX_PUBLIC_URL", "http://127.0.0.1:8501").rstrip("/")


def build_return_url(sid: str = "", payment_id: str = "") -> str:
    from urllib.parse import quote

    base = public_app_url()
    if sid:
        url = f"{base}/?sid={quote(sid)}"
    else:
        url = f"{base}/"
    if payment_id:
        sep = "&" if "?" in url else "?"
        url += f"{sep}payment_id={quote(payment_id)}"
    return url


def get_latest_pending_payment(user_email: str) -> dict | None:
    """Последний ожидающий платёж пользователя (для return_url без payment_id)."""
    data = _load_payments()
    latest = None
    latest_ts = ""
    for rec in data["payments"].values():
        if rec.get("user_email") != user_email:
            continue
        if rec.get("status") not in ("pending", "waiting_for_capture"):
            continue
        ts = rec.get("created_at") or ""
        if ts >= latest_ts:
            latest_ts = ts
            latest = rec
    return latest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_payments() -> dict:
    os.makedirs(os.path.dirname(PAYMENTS_FILE), exist_ok=True)
    if not os.path.isfile(PAYMENTS_FILE):
        return {"payments": {}}
    with open(PAYMENTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("payments", {})
    return data


def _save_payments(data: dict) -> None:
    os.makedirs(os.path.dirname(PAYMENTS_FILE), exist_ok=True)
    with open(PAYMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def register_payment(
    payment_id: str,
    user_email: str,
    tariff_id: str = "",
    amount: float = 0,
    status: str = "pending",
    *,
    purpose: str = PURPOSE_TARIFF,
    amount_tokens: int | None = None,
) -> dict:
    data = _load_payments()
    rec = {
        "payment_id": payment_id,
        "user_email": user_email,
        "tariff_id": tariff_id,
        "amount": amount,
        "status": status,
        "purpose": purpose,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    if purpose == PURPOSE_FLOW_TOKENS and amount_tokens is not None:
        rec["amount_tokens"] = int(amount_tokens)
    data["payments"][payment_id] = rec
    _save_payments(data)
    return rec


def get_payment_record(payment_id: str) -> dict | None:
    return _load_payments()["payments"].get(payment_id)


def update_payment_status(payment_id: str, status: str) -> dict | None:
    data = _load_payments()
    rec = data["payments"].get(payment_id)
    if not rec:
        return None
    rec["status"] = status
    rec["updated_at"] = _now_iso()
    _save_payments(data)
    return rec


def load_accounts() -> dict:
    if not os.path.isfile(ACCOUNTS_FILE):
        return {}
    with open(ACCOUNTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_accounts(accounts: dict) -> None:
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def _get_user_folder(user_email: str) -> str:
    acc = load_accounts().get(user_email) or {}
    return (acc.get("folder") or "").strip()


EXEMPT_ADMIN_EMAIL = os.environ.get("SINLEX_ADMIN_EMAIL", "admin@sinlex.tech").strip().lower()


def is_tariff_exempt(user_email: str) -> bool:
    """Эксклюзивный доступ: без тарифов, лимитов и стены оплаты."""
    if not user_email:
        return False
    acc = load_accounts().get(user_email) or {}
    if acc.get("tariff_exempt"):
        return True
    return user_email.strip().lower() == EXEMPT_ADMIN_EMAIL


def _exempt_access_state(user_email: str) -> dict:
    return {
        "user_email": user_email,
        "user_folder": _get_user_folder(user_email),
        "tariff_id": "exempt",
        "tariff_name": "Эксклюзивный доступ",
        "tariff_active_until": "",
        "active": True,
        "project_limit": None,
        "projects_uploaded_total": 0,
        "projects_limit_reached": False,
        "reason": "",
        "tariff_exempt": True,
    }


def _user_payment_file(user_email: str) -> str | None:
    folder = _get_user_folder(user_email)
    if not folder:
        return None
    os.makedirs(USER_PAYMENTS_DIR, exist_ok=True)
    safe = folder.replace("/", "_").replace("\\", "_")
    return os.path.join(USER_PAYMENTS_DIR, f"{safe}.json")


def _load_user_payment(user_email: str) -> dict:
    path = _user_payment_file(user_email)
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_user_payment(user_email: str, payload: dict) -> None:
    path = _user_payment_file(user_email)
    if not path:
        raise ValueError(f"Не найден каталог пользователя для {user_email}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _profile_flow_balance_rub(profile: dict) -> int:
    """Баланс «Поток» в рублях из профиля (с fallback на legacy flow_tokens)."""
    if not profile:
        return 0
    if FLOW_BALANCE_RUB_KEY in profile:
        try:
            return max(0, int(profile.get(FLOW_BALANCE_RUB_KEY) or 0))
        except (TypeError, ValueError):
            return 0
    try:
        legacy_tokens = max(0, int(profile.get("flow_tokens", 0)))
    except (TypeError, ValueError):
        legacy_tokens = 0
    if legacy_tokens <= 0:
        return 0
    return legacy_tokens * FLOW_RUB_PER_TOKEN


def get_flow_balance_rub(user_email: str) -> int:
    """Баланс режима «Поток» в рублях."""
    if not user_email:
        return 0
    return _profile_flow_balance_rub(_load_user_payment(user_email))


def get_flow_token_balance(user_email: str) -> int:
    """Совместимость: баланс в рублях (понятие токенов упразднено)."""
    return get_flow_balance_rub(user_email)


def _set_profile_flow_balance_rub(profile: dict, balance_rub: int) -> None:
    profile[FLOW_BALANCE_RUB_KEY] = max(0, int(balance_rub))
    profile.pop("flow_tokens", None)


def credit_flow_tokens(
    user_email: str,
    amount: int,
    payment_id: str,
    *,
    source: str = "yookassa",
) -> dict:
    """Зачислить рубли на баланс «Поток» (идемпотентно по payment_id)."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    profile = _load_user_payment(user_email) or {}
    txs = profile.setdefault("transactions", [])
    if any(t.get("payment_id") == payment_id for t in txs):
        out = {
            "already_credited": True,
            "balance": get_flow_token_balance(user_email),
            "payment_id": payment_id,
            "purpose": PURPOSE_FLOW_TOKENS,
        }
        try:
            out["released"] = release_flow_pending_queue(user_email)
        except Exception:
            out["released"] = []
        return out
    new_bal = get_flow_balance_rub(user_email) + amount
    _set_profile_flow_balance_rub(profile, new_bal)
    txs.append(
        {
            "date": _now_iso(),
            "type": "deposit",
            "amount": amount,
            "source": source,
            "payment_id": payment_id,
            "purpose": PURPOSE_FLOW_TOKENS,
        }
    )
    profile["user_email"] = user_email
    profile["user_folder"] = _get_user_folder(user_email)
    profile["updated_at"] = _now_iso()
    _save_user_payment(user_email, profile)
    result = {
        "credited": amount,
        "balance": profile[FLOW_BALANCE_RUB_KEY],
        "payment_id": payment_id,
        "purpose": PURPOSE_FLOW_TOKENS,
    }
    try:
        result["released"] = release_flow_pending_queue(user_email)
    except Exception:
        result["released"] = []
    return result


def debit_flow_tokens(
    user_email: str,
    amount: int,
    *,
    source: str = "flow_analysis",
    project: str = "",
    task_id: str = "",
    pending_id: str = "",
) -> dict:
    """Списать рубли с баланса «Поток» (идемпотентно по source+task_id)."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("amount must be positive")
    balance = get_flow_token_balance(user_email)
    if balance < amount:
        return {"ok": False, "reason": "insufficient_balance", "balance": balance}
    profile = _load_user_payment(user_email) or {}
    txs = profile.setdefault("transactions", [])
    idem_key = f"{source}:{task_id}" if task_id else ""
    if task_id and any(
        t.get("type") == "spend"
        and t.get("source") == source
        and t.get("task_id") == task_id
        for t in txs
    ):
        return {
            "ok": True,
            "already_debited": True,
            "balance": get_flow_token_balance(user_email),
            "debited": 0,
        }
    _set_profile_flow_balance_rub(profile, balance - amount)
    spend_rec = {
        "date": _now_iso(),
        "type": "spend",
        "amount": -amount,
        "source": source,
        "task_id": task_id,
        "purpose": PURPOSE_FLOW_TOKENS,
    }
    if pending_id:
        spend_rec["pending_id"] = pending_id
    if project:
        spend_rec["project"] = project
    txs.append(spend_rec)
    profile["user_email"] = user_email
    profile["user_folder"] = _get_user_folder(user_email)
    profile["updated_at"] = _now_iso()
    _save_user_payment(user_email, profile)
    return {"ok": True, "balance": profile[FLOW_BALANCE_RUB_KEY], "debited": amount}


def _flow_pending_file(user_email: str) -> str | None:
    folder = _get_user_folder(user_email)
    if not folder:
        return None
    os.makedirs(FLOW_PENDING_DIR, exist_ok=True)
    safe = folder.replace("/", "_").replace("\\", "_")
    return os.path.join(FLOW_PENDING_DIR, f"{safe}.json")


def _load_flow_pending(user_email: str) -> dict:
    fpath = _flow_pending_file(user_email)
    if not fpath or not os.path.isfile(fpath):
        return {"queue": []}
    try:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"queue": []}
        data.setdefault("queue", [])
        return data
    except Exception:
        return {"queue": []}


def _save_flow_pending(user_email: str, data: dict) -> None:
    fpath = _flow_pending_file(user_email)
    if not fpath:
        raise ValueError(f"Не найден каталог пользователя для {user_email}")
    data["user_email"] = user_email
    data["user_folder"] = _get_user_folder(user_email)
    data["updated_at"] = _now_iso()
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_flow_pending_by_task_id(user_email: str, task_id: str) -> dict | None:
    if not task_id:
        return None
    for item in _load_flow_pending(user_email).get("queue") or []:
        if item.get("task_id") == task_id:
            return item
    return None


def enqueue_flow_pending(
    user_email: str,
    *,
    task_id: str,
    project_name: str,
    project_slug: str,
    tokens_required: int,  # рубли (legacy имя параметра)
    rub_required: int | None = None,
    result_payload: dict,
) -> str:
    data = _load_flow_pending(user_email)
    queue = data.setdefault("queue", [])
    for item in queue:
        if item.get("task_id") == task_id:
            return str(item.get("pending_id") or "")
    pending_id = f"fp_{uuid.uuid4().hex[:12]}"
    queue.append(
        {
            "pending_id": pending_id,
            "task_id": task_id,
            "project_name": project_name,
            "project_slug": project_slug,
            "created_at": _now_iso(),
            "rub_required": int(rub_required if rub_required is not None else tokens_required),
            "tokens_required": int(rub_required if rub_required is not None else tokens_required),
            "result_payload": result_payload,
        }
    )
    _save_flow_pending(user_email, data)
    return pending_id


def release_flow_pending_queue(user_email: str) -> list[dict]:
    """FIFO: списать и снять pending, пока хватает баланса."""
    data = _load_flow_pending(user_email)
    queue = list(data.get("queue") or [])
    released: list[dict] = []
    idx = 0
    while idx < len(queue):
        item = queue[idx]
        need = int(item.get("rub_required") or item.get("tokens_required") or 0)
        balance = get_flow_token_balance(user_email)
        if need > 0 and balance >= need:
            debit = debit_flow_tokens(
                user_email,
                need,
                source="flow_analysis",
                project=str(item.get("project_name") or ""),
                task_id=str(item.get("task_id") or ""),
                pending_id=str(item.get("pending_id") or ""),
            )
            if debit.get("ok"):
                rel = {
                    "pending_id": item.get("pending_id"),
                    "task_id": item.get("task_id"),
                    "project_name": item.get("project_name"),
                    "project_slug": item.get("project_slug"),
                    "tokens_debited": need,
                    "result_payload": item.get("result_payload"),
                }
                released.append(rel)
                try:
                    from hybrid_analysis import apply_released_pending_to_job

                    apply_released_pending_to_job(
                        str(item.get("project_name") or ""),
                        _get_user_folder(user_email),
                        str(item.get("task_id") or ""),
                        item.get("result_payload") or {},
                        tokens_debited=need,
                    )
                except Exception:
                    pass
                queue.pop(idx)
                continue
        idx += 1
    data["queue"] = queue
    _save_flow_pending(user_email, data)
    return released


def _payment_to_dict(payment_obj: Any | None) -> dict:
    if not payment_obj:
        return {}
    if isinstance(payment_obj, dict):
        return payment_obj
    out: dict[str, Any] = {}
    for key in ("id", "status", "description", "paid", "created_at", "captured_at"):
        val = getattr(payment_obj, key, None)
        if val is not None:
            out[key] = val
    amount = getattr(payment_obj, "amount", None)
    if amount is not None:
        out["amount"] = {
            "value": getattr(amount, "value", None),
            "currency": getattr(amount, "currency", None),
        }
    metadata = getattr(payment_obj, "metadata", None)
    if metadata is not None:
        out["metadata"] = metadata
    confirmation = getattr(payment_obj, "confirmation", None)
    if confirmation is not None:
        out["confirmation"] = {
            "type": getattr(confirmation, "type", None),
            "confirmation_url": getattr(confirmation, "confirmation_url", None),
        }
    return out




def is_paid_tariff(tariff_id: str | None) -> bool:
    return bool(tariff_id) and tariff_id in TARIFF_PLANS and tariff_id != TRIAL_TARIFF_ID


def iter_paid_tariff_plans():
    """Тарифы, доступные для оплаты (без пробного)."""
    for tid, plan in TARIFF_PLANS.items():
        if is_paid_tariff(tid):
            yield tid, plan


def _resolve_account_email(user_email: str) -> str | None:
    email = (user_email or "").strip()
    if not email:
        return None
    accounts = load_accounts()
    if email in accounts:
        return email
    low = email.lower()
    if low in accounts:
        return low
    return None


def activate_trial_access(user_email: str) -> dict:
    """Тарификация отключена — пробный тариф не выдаётся."""
    email = _resolve_account_email(user_email)
    if not email:
        return {}
    return get_user_access_state(email)


def activate_tariff(
    user_email: str,
    tariff_id: str,
    payment_id: str,
    yookassa_data: dict | None = None,
) -> dict:
    """Привязать успешный платёж к аккаунту и активировать тариф."""
    if not is_paid_tariff(tariff_id):
        raise ValueError(f"Неизвестный тариф: {tariff_id}")
    accounts = load_accounts()
    acc = accounts.get(user_email)
    if not acc:
        raise ValueError(f"Пользователь не найден: {user_email}")

    until = datetime.now(timezone.utc) + timedelta(days=TARIFF_PERIOD_DAYS)
    acc["tariff"] = tariff_id
    acc["tariff_name"] = TARIFF_PLANS[tariff_id]["name"]
    acc["tariff_active_until"] = until.isoformat()
    acc["last_payment_id"] = payment_id
    acc["tariff_activated_at"] = _now_iso()
    accounts[user_email] = acc
    save_accounts(accounts)
    update_payment_status(payment_id, "succeeded")
    profile = _load_user_payment(user_email) or {}
    limit = _effective_project_limit(profile, tariff_id)
    old_keys = list(profile.get("project_keys_used") or [])
    old_total = int(profile.get("projects_uploaded_total") or 0)
    profile.update(
        {
            "user_email": user_email,
            "user_folder": _get_user_folder(user_email),
            "payment_id": payment_id,
            "tariff_id": tariff_id,
            "tariff_name": TARIFF_PLANS[tariff_id]["name"],
            "amount": TARIFF_PLANS[tariff_id]["amount"],
            "currency": "RUB",
            "paid_at": _now_iso(),
            "tariff_activated_at": acc["tariff_activated_at"],
            "tariff_active_until": acc["tariff_active_until"],
            "tariff_period_days": TARIFF_PERIOD_DAYS,
            "project_limit": limit,
            "projects_uploaded_total": old_total,
            "projects_limit_reached": bool(
                limit is not None and old_total >= limit
            ),
            "yookassa_response": yookassa_data or {},
            "updated_at": _now_iso(),
        }
    )
    if old_keys:
        profile["project_keys_used"] = old_keys
    _save_user_payment(user_email, profile)
    reconcile_project_usage(user_email)
    return {
        "user_email": user_email,
        "tariff": tariff_id,
        "tariff_name": acc["tariff_name"],
        "tariff_active_until": acc["tariff_active_until"],
        "payment_id": payment_id,
    }


def _build_receipt(amount: float, description: str, user_email: str) -> dict:
    """Чек 54-ФЗ для ЮKassa (обязателен для live-магазина)."""
    vat_code = os.environ.get("YOOKASSA_VAT_CODE", "1").strip() or "1"
    customer: dict[str, str] = {"email": user_email[:256]}
    acc = load_accounts().get(user_email) or {}
    company = (acc.get("company_name") or "").strip()
    if company:
        customer["full_name"] = company[:256]
    return {
        "customer": customer,
        "items": [
            {
                "description": (description or "Подписка Sinlex")[:128],
                "quantity": "1.00",
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "vat_code": vat_code,
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }
        ],
    }


def create_payment(
    amount: float,
    description: str,
    return_url: str,
    user_email: str,
    tariff_id: str,
) -> tuple[str, str]:
    """Создать платёж ЮKassa. Возвращает (confirmation_url, payment_id)."""
    _ensure_yookassa()
    from yookassa import Payment

    amount_str = f"{amount:.2f}"
    payment = Payment.create(
        {
            "amount": {"value": amount_str, "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description[:128],
            "metadata": {
                "user_email": user_email,
                "tariff_id": tariff_id,
                "purpose": PURPOSE_TARIFF,
            },
            "receipt": _build_receipt(amount, description, user_email),
        },
        idempotency_key=f"{user_email}:{tariff_id}:{int(time.time())}",
    )
    register_payment(
        payment.id,
        user_email,
        tariff_id,
        amount,
        status=payment.status,
        purpose=PURPOSE_TARIFF,
    )
    return payment.confirmation.confirmation_url, payment.id


def create_flow_topup_payment(
    user_email: str,
    amount_rub: int,
    return_url: str,
) -> tuple[str, str]:
    """Создать платёж ЮKassa для пополнения баланса «Поток» (₽)."""
    amount_rub = int(amount_rub)
    if amount_rub < FLOW_TOPUP_MIN_AMOUNT:
        raise ValueError(
            f"Минимальное пополнение — {FLOW_TOPUP_MIN_AMOUNT} ₽"
        )
    if not _get_user_folder(user_email):
        raise ValueError(f"Пользователь не найден: {user_email}")
    _ensure_yookassa()
    from yookassa import Payment

    amount = float(amount_rub)
    description = f"Пополнение баланса Поток — {amount_rub} ₽"
    amount_str = f"{amount:.2f}"
    payment = Payment.create(
        {
            "amount": {"value": amount_str, "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description[:128],
            "metadata": {
                "user_email": user_email,
                "purpose": PURPOSE_FLOW_TOKENS,
                "amount_rub": str(amount_rub),
                "amount_balance_rub": str(amount_rub),
            },
            "receipt": _build_receipt(amount, description, user_email),
        },
        idempotency_key=f"{user_email}:flow:{amount_rub}:{int(time.time())}",
    )
    register_payment(
        payment.id,
        user_email,
        tariff_id="",
        amount=amount,
        status=payment.status,
        purpose=PURPOSE_FLOW_TOKENS,
        amount_tokens=amount_rub,
    )
    return payment.confirmation.confirmation_url, payment.id


def process_flow_topup_succeeded(
    payment_id: str,
    metadata: dict | None = None,
    yookassa_obj: dict | None = None,
) -> dict | None:
    """Зачислить рубли после успешной оплаты пополнения."""
    rec = get_payment_record(payment_id)
    meta = metadata or {}
    user_email = (meta.get("user_email") or (rec or {}).get("user_email") or "").strip()
    amount_tokens_raw = meta.get("amount_tokens") or (rec or {}).get("amount_tokens")
    if not user_email:
        status = check_payment(payment_id)
        if status != "succeeded":
            return None
        _ensure_yookassa()
        from yookassa import Payment

        payment = Payment.find_one(payment_id)
        meta = payment.metadata or {}
        user_email = (meta.get("user_email") or "").strip()
        amount_tokens_raw = meta.get("amount_tokens")
        if not yookassa_obj:
            yookassa_obj = _payment_to_dict(payment)
    if not user_email:
        return None
    amount_rub = 0
    amount_rub_meta = meta.get("amount_rub") or meta.get("amount_balance_rub")
    if amount_rub_meta is not None and str(amount_rub_meta).strip().isdigit():
        amount_rub = int(amount_rub_meta)
    elif rec:
        amount_rub = int(float(rec.get("amount") or 0))
    if amount_rub <= 0:
        try:
            legacy = int(amount_tokens_raw)
        except (TypeError, ValueError):
            legacy = 0
        if legacy > 0:
            pay_rub = int(float((rec or {}).get("amount") or 0))
            if pay_rub > 0 and legacy == pay_rub:
                amount_rub = pay_rub
            elif legacy < pay_rub or pay_rub == 0:
                amount_rub = legacy * FLOW_RUB_PER_TOKEN
            else:
                amount_rub = pay_rub
    if rec and rec.get("status") == "succeeded":
        bal = get_flow_token_balance(user_email)
        txs = (_load_user_payment(user_email) or {}).get("transactions") or []
        if any(t.get("payment_id") == payment_id for t in txs):
            return {
                "already_credited": True,
                "balance": bal,
                "payment_id": payment_id,
                "purpose": PURPOSE_FLOW_TOKENS,
            }
    status = check_payment(payment_id)
    if status != "succeeded":
        return None
    update_payment_status(payment_id, "succeeded")
    return credit_flow_tokens(user_email, amount_rub, payment_id)


def check_payment(payment_id: str) -> str:
    _ensure_yookassa()
    from yookassa import Payment

    payment = Payment.find_one(payment_id)
    update_payment_status(payment_id, payment.status)
    return payment.status


def process_payment_succeeded(
    payment_id: str,
    metadata: dict | None = None,
    yookassa_obj: dict | None = None,
) -> dict | None:
    """Обработать успешную оплату: тариф или пополнение токенов «Поток»."""
    rec = get_payment_record(payment_id)
    meta = metadata or {}
    purpose = (
        meta.get("purpose")
        or (rec or {}).get("purpose")
        or PURPOSE_TARIFF
    )
    if purpose == PURPOSE_FLOW_TOKENS:
        return process_flow_topup_succeeded(payment_id, meta, yookassa_obj=yookassa_obj)
    user_email = meta.get("user_email") or (rec or {}).get("user_email")
    tariff_id = meta.get("tariff_id") or (rec or {}).get("tariff_id")
    if not user_email or not tariff_id:
        status = check_payment(payment_id)
        if status != "succeeded":
            return None
        _ensure_yookassa()
        from yookassa import Payment

        payment = Payment.find_one(payment_id)
        meta = payment.metadata or {}
        user_email = meta.get("user_email") or user_email
        tariff_id = meta.get("tariff_id") or tariff_id
        if not yookassa_obj:
            yookassa_obj = _payment_to_dict(payment)
    if not user_email or not tariff_id:
        return None
    if rec and rec.get("status") == "succeeded":
        accounts = load_accounts()
        if accounts.get(user_email, {}).get("last_payment_id") == payment_id:
            return {
                "already_active": True,
                "user_email": user_email,
                "tariff": tariff_id,
                "payment_id": payment_id,
            }
    status = check_payment(payment_id)
    if status != "succeeded":
        return None
    return activate_tariff(user_email, tariff_id, payment_id, yookassa_data=yookassa_obj or {})


def is_activation_result(result: dict | None) -> bool:
    """Успешная обработка платежа: тариф или пополнение токенов."""
    if not result:
        return False
    if result.get("purpose") == PURPOSE_FLOW_TOKENS:
        return result.get("balance") is not None
    if result.get("already_active") or result.get("already_credited"):
        return True
    return bool(result.get("tariff") or result.get("tariff_name"))


def handle_webhook(body: dict) -> dict:
    """Обработка уведомления ЮKassa."""
    event = body.get("event") or ""
    obj = body.get("object") or {}
    payment_id = obj.get("id")
    if not payment_id:
        return {"ok": False, "reason": "no payment id"}

    meta = obj.get("metadata") or {}
    status = obj.get("status") or ""

    if event == "payment.succeeded" or status == "succeeded":
        result = process_payment_succeeded(payment_id, meta, yookassa_obj=obj)
        return {"ok": True, "event": event, "result": result}
    if event in ("payment.canceled", "payment.waiting_for_capture") or status in ("canceled", "pending"):
        update_payment_status(payment_id, status or "canceled")
        return {"ok": True, "event": event, "status": status}
    return {"ok": True, "event": event, "ignored": True}


def get_user_tariff_info(user_email: str) -> dict | None:
    acc = load_accounts().get(user_email)
    if not acc or not acc.get("tariff"):
        return None
    until_raw = acc.get("tariff_active_until")
    active = True
    if until_raw:
        try:
            until = datetime.fromisoformat(until_raw.replace("Z", "+00:00"))
            active = until > datetime.now(timezone.utc)
        except ValueError:
            pass
    plan = TARIFF_PLANS.get(acc.get("tariff", ""), {})
    return {
        "tariff": acc.get("tariff"),
        "tariff_name": acc.get("tariff_name") or plan.get("name", ""),
        "tariff_active_until": until_raw,
        "active": active,
        "last_payment_id": acc.get("last_payment_id"),
    }


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _collect_keys_in_user_storage(user_dir: str) -> set[str]:
    """Ключи проектов в одной корне (projects или casting)."""
    keys: set[str] = set()
    if not user_dir or not os.path.isdir(user_dir):
        return keys
    projects_file = os.path.join(user_dir, "projects.json")
    if os.path.isfile(projects_file):
        try:
            with open(projects_file, encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("projects", []):
                name = (p.get("name") or "").strip()
                if name:
                    keys.add(normalize_project_key(name))
        except (OSError, json.JSONDecodeError):
            pass
    for entry in os.listdir(user_dir):
        if entry in ("projects.json",) or entry.startswith("."):
            continue
        if os.path.isdir(os.path.join(user_dir, entry)):
            keys.add(entry)
    return keys


def _collect_project_keys_on_disk(user_email: str) -> set[str]:
    """Слоты тарифа: 3D-проекты + литьевые проекты (общий счётчик)."""
    folder = _get_user_folder(user_email)
    if not folder:
        return set()
    keys: set[str] = set()
    keys |= _collect_keys_in_user_storage(os.path.join(PROJECTS_ROOT, folder))
    keys |= _collect_keys_in_user_storage(os.path.join(CASTING_ROOT, folder))
    return keys


def reconcile_project_usage(user_email: str) -> dict:
    """Тарификация отключена — счётчик проектов не ограничивается."""
    return {}


def is_new_project_slot(user_email: str, project_name: str) -> bool:
    return False


def get_user_access_state(user_email: str) -> dict:
    return {
        "user_email": user_email,
        "user_folder": _get_user_folder(user_email),
        "tariff_id": "",
        "tariff_name": "",
        "tariff_active_until": "",
        "active": True,
        "project_limit": None,
        "projects_uploaded_total": len(_collect_project_keys_on_disk(user_email)),
        "projects_limit_reached": False,
        "reason": "",
    }


def can_create_new_project(user_email: str, is_new_project: bool) -> dict:
    state = get_user_access_state(user_email)
    return {"allowed": True, "state": state}


def register_project_created(user_email: str, project_name: str) -> dict:
    return get_user_access_state(user_email)


def get_user_balance_snapshot(user_email: str) -> dict:
    return {"amount": 0, "label": "—", "details": "Без ограничений"}
