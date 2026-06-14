"""YooKassa payment endpoints."""
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/payments", tags=["payments"])


class PaymentCreateRequest(BaseModel):
    tariff_id: str
    return_sid: str = ""


class FlowTopupRequest(BaseModel):
    amount: int = Field(..., ge=1, description="Сумма пополнения в рублях")
    return_sid: str = ""


@router.get("/plans")
async def payments_plans():
    return {"plans": []}


@router.get("/flow-balance")
async def payments_flow_balance(x_user_email: str = Header(None)):
    import payment as pay

    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(401, "X-User-Email header required")
    exempt = pay.is_tariff_exempt(email)
    return {
        "balance": pay.get_flow_token_balance(email),
        "exempt": exempt,
    }


@router.post("/flow-pending/release")
async def payments_flow_pending_release(x_user_email: str = Header(None)):
    import payment as pay

    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(401, "X-User-Email header required")
    released = pay.release_flow_pending_queue(email)
    return {
        "released": released,
        "balance": pay.get_flow_token_balance(email),
    }


@router.post("/flow-topup")
async def payments_flow_topup(data: FlowTopupRequest, x_user_email: str = Header(None)):
    import payment as pay

    pay.load_env()
    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(401, "X-User-Email header required")
    if data.amount < pay.FLOW_TOPUP_MIN_AMOUNT:
        raise HTTPException(
            400,
            f"Минимальное пополнение — {pay.FLOW_TOPUP_MIN_AMOUNT} ₽",
        )
    sid = (data.return_sid or "").strip()
    return_url = pay.build_return_url(sid=sid)
    try:
        confirmation_url, payment_id = pay.create_flow_topup_payment(
            email, data.amount, return_url
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Ошибка создания платежа: {exc}") from exc
    tokens = pay.flow_rub_to_tokens(data.amount)
    return {
        "payment_id": payment_id,
        "confirmation_url": confirmation_url,
        "return_url": return_url,
        "amount_rub": data.amount,
        "amount": data.amount,
        "tokens_to_credit": tokens,
        "purpose": pay.PURPOSE_FLOW_TOKENS,
    }


@router.post("/create")
async def payments_create(data: PaymentCreateRequest, x_user_email: str = Header(None)):
    raise HTTPException(410, "Тарифы отключены")
    import payment as pay

    pay.load_env()
    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(401, "X-User-Email header required")
    if not pay.is_paid_tariff(data.tariff_id):
        raise HTTPException(400, "Неизвестный тариф")
    plan = pay.TARIFF_PLANS[data.tariff_id]
    sid = (data.return_sid or "").strip()
    return_url = pay.build_return_url(sid=sid)
    try:
        confirmation_url, payment_id = pay.create_payment(
            amount=float(plan["amount"]),
            description=plan["description"],
            return_url=return_url,
            user_email=email,
            tariff_id=data.tariff_id,
        )
    except Exception as exc:
        raise HTTPException(500, f"Ошибка создания платежа: {exc}") from exc
    return {
        "payment_id": payment_id,
        "confirmation_url": confirmation_url,
        "return_url": return_url,
        "tariff_id": data.tariff_id,
        "amount": plan["amount"],
        "purpose": pay.PURPOSE_TARIFF,
    }


@router.get("/pending")
async def payments_pending(x_user_email: str = Header(None)):
    import payment as pay

    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(401, "X-User-Email header required")
    return {"pending": pay.get_latest_pending_payment(email)}


@router.get("/status/{payment_id}")
async def payments_status(payment_id: str, x_user_email: str = Header(None)):
    import payment as pay

    pay.load_env()
    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(401, "X-User-Email header required")
    rec = pay.get_payment_record(payment_id)
    if rec and rec.get("user_email") != email:
        raise HTTPException(403, "Платёж принадлежит другому пользователю")
    try:
        status = pay.check_payment(payment_id)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return {
        "payment_id": payment_id,
        "status": status,
        "record": rec,
        "tariff": pay.get_user_tariff_info(email),
        "flow_balance": pay.get_flow_token_balance(email),
    }


@router.post("/confirm/{payment_id}")
async def payments_confirm(payment_id: str, x_user_email: str = Header(None)):
    import payment as pay

    pay.load_env()
    email = (x_user_email or "").strip()
    if not email:
        raise HTTPException(401, "X-User-Email header required")
    rec = pay.get_payment_record(payment_id)
    if rec and rec.get("user_email") != email:
        raise HTTPException(403, "Платёж принадлежит другому пользователю")
    result = pay.process_payment_succeeded(payment_id)
    if not pay.is_activation_result(result):
        status = pay.check_payment(payment_id)
        raise HTTPException(409, f"Платёж не завершён (статус: {status})")
    return {"ok": True, "result": result}


@router.post("/webhook/yookassa")
async def payments_webhook_yookassa(request: Request):
    import payment as pay

    pay.load_env()
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    return pay.handle_webhook(body)
