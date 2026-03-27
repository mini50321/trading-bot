from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.db.mongo import mongo
from app.observability.log import configure_logging, log_event, log_exception
from app.domain.execution import WebhookSignalIn
from app.repo.signals import signals_repo
from app.repo.system import system_repo
from app.repo.users import users_repo
from app.repo.affiliate import affiliate_repo
from app.repo.credentials import credentials_repo
from app.repo.tokens import tokens_repo
from app.services.pocketoption_auth import pocketoption_auth
from app.services.settlement_worker import settlement_worker
from app.services.trade_engine import trade_engine
from app.services.affiliate_email import detect_email_confirmation
from app.services.token_deposit import (
    deposit_dedupe_key,
    deposit_tokens_for_amount,
    detect_deposit_postback,
    parse_deposit_amount_usd,
)
from app.services.strategy_worker import strategy_worker
from app.web.webhook_guard import (
    extract_client_ip,
    parse_webhook_json,
    verify_webhook_hmac_sha256,
    webhook_rate_limiter,
)


class TokenAdjustIn(BaseModel):
    telegram_id: int
    delta: int
    reason: str = "admin_api"


app = FastAPI()


async def _admin_auth(x_api_key: str | None = Header(default=None)) -> bool:
    key = get_settings().require_admin_api_key()
    if not x_api_key or x_api_key != key:
        raise HTTPException(status_code=401, detail="unauthorized")
    return True


@app.on_event("startup")
async def _startup():
    configure_logging(level=get_settings().log_level)
    await mongo.connect()
    await pocketoption_auth.start()
    await settlement_worker.start()
    await strategy_worker.start()


@app.on_event("shutdown")
async def _shutdown():
    await settlement_worker.stop()
    await strategy_worker.stop()
    await pocketoption_auth.close()
    await mongo.close()


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None, alias="x-webhook-secret"),
    x_webhook_signature: str | None = Header(default=None, alias="x-webhook-signature"),
):
    s = get_settings()
    ip = extract_client_ip(
        request, trust_x_forwarded_for=s.webhook_trust_x_forwarded_for
    )
    if not await webhook_rate_limiter.allow(
        f"webhook:{ip}", limit=int(s.webhook_rate_limit_per_minute), window_sec=60.0
    ):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    body = await request.body()

    hmac_secret = s.optional_webhook_hmac_secret()
    if hmac_secret:
        if not verify_webhook_hmac_sha256(
            secret=hmac_secret, body=body, signature_header=x_webhook_signature
        ):
            raise HTTPException(status_code=401, detail="invalid_signature")

    shared = s.optional_webhook_secret()
    if shared:
        if not x_webhook_secret or x_webhook_secret != shared:
            raise HTTPException(status_code=401, detail="unauthorized")

    data = parse_webhook_json(body)
    try:
        signal = WebhookSignalIn.model_validate(data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    created, stored = await signals_repo.store(signal)
    if not created:
        log_event(
            "webhook.duplicate",
            signal_id=stored.signal_id,
            symbol=stored.symbol,
            source=stored.source,
            client_ip=ip,
        )
        return {"status": "duplicate", "signal": stored.model_dump()}
    try:
        result = await trade_engine.on_signal(stored)
        log_event(
            "webhook.accepted",
            signal_id=stored.signal_id,
            symbol=stored.symbol,
            direction=stored.direction,
            eligible=result.get("eligible"),
            client_ip=ip,
        )
        return {"status": "accepted", "signal": stored.model_dump(), "result": result}
    except Exception as e:
        log_exception(
            "webhook.failed",
            e,
            signal_id=stored.signal_id,
            symbol=stored.symbol,
            client_ip=ip,
        )
        raise HTTPException(status_code=500, detail=type(e).__name__)


@app.post("/affiliate/postback")
async def affiliate_postback(
    request: Request,
    x_affiliate_secret: str | None = Header(default=None, alias="x-affiliate-secret"),
    x_affiliate_signature: str | None = Header(default=None, alias="x-affiliate-signature"),
):
    s = get_settings()
    body = await request.body()

    hmac_secret = s.optional_affiliate_postback_hmac_secret()
    if hmac_secret:
        if not verify_webhook_hmac_sha256(secret=hmac_secret, body=body, signature_header=x_affiliate_signature):
            raise HTTPException(status_code=401, detail="invalid_signature")

    shared = s.optional_affiliate_postback_secret()
    if shared:
        if not x_affiliate_secret or x_affiliate_secret != shared:
            raise HTTPException(status_code=401, detail="unauthorized")

    data = parse_webhook_json(body)
    await affiliate_repo.record_event(data)
    email = str(data.get("email") or data.get("user_email") or "").strip().lower()
    event_hint = (
        data.get("event")
        or data.get("type")
        or data.get("action")
        or data.get("postback_type")
        or data.get("event_type")
    )
    event_label = str(event_hint).strip().lower() if event_hint is not None else ""
    # Verification only: mark that PocketPartners (or similar) notified us about this email.
    # User balances and profile are read from PocketOption APIs, not from postbacks.
    patch: dict[str, Any] = {
        "postback_received": True,
        "last_postback_at": datetime.now(timezone.utc),
        "last_postback_event": event_label or None,
    }
    confirmed = bool(
        email
        and detect_email_confirmation(
            event_label,
            data,
            s.affiliate_email_confirm_event_list(),
        )
    )
    if confirmed:
        patch["email_confirmed"] = True
        patch["email_confirmed_at"] = datetime.now(timezone.utc)
    if email:
        await affiliate_repo.upsert_account_by_email(email, patch)

    if email and s.token_system_enabled:
        if detect_deposit_postback(event_label, data, s.token_deposit_event_list()):
            amt = parse_deposit_amount_usd(data)
            if amt is not None:
                ntok = deposit_tokens_for_amount(amt, s)
                if ntok > 0:
                    dk = deposit_dedupe_key(email, event_label, data)
                    acc = await affiliate_repo.get_account_by_email(email)
                    tid = (acc or {}).get("telegram_id")
                    meta_tok = {
                        "email": email,
                        "amount_usd": amt,
                        "event": event_label,
                    }
                    if tid:
                        credited = await tokens_repo.add_tokens(
                            int(tid),
                            ntok,
                            "affiliate_deposit",
                            meta_tok,
                            dedupe_key=dk,
                        )
                        log_event(
                            "tokens.credited",
                            telegram_id=int(tid),
                            tokens=ntok,
                            email=email,
                            credited=credited,
                            dedupe=bool(dk),
                        )
                    else:
                        await affiliate_repo.add_pending_tokens(email, ntok)
                        log_event(
                            "tokens.pending",
                            email=email,
                            tokens=ntok,
                            dedupe_key=dk,
                        )

    log_event(
        "affiliate.postback",
        email=email or None,
        event=event_label or None,
        email_confirmed=confirmed,
    )
    return {"ok": True}


@app.get("/admin/system")
async def admin_system(_: bool = Depends(_admin_auth)):
    return {"global_trading_enabled": await system_repo.get_global_trading_enabled()}


@app.post("/admin/system/global_on")
async def admin_global_on(_: bool = Depends(_admin_auth)):
    await system_repo.set_global_trading_enabled(True)
    return {"global_trading_enabled": True}


@app.post("/admin/system/global_off")
async def admin_global_off(_: bool = Depends(_admin_auth)):
    await system_repo.set_global_trading_enabled(False)
    return {"global_trading_enabled": False}


@app.get("/admin/users")
async def admin_users(_: bool = Depends(_admin_auth), limit: int = 50):
    limit = max(1, min(500, int(limit)))
    users = await users_repo.list_users(limit=limit)
    return {"users": [u.model_dump() for u in users]}


@app.get("/admin/user_snapshot")
async def admin_user_snapshot(telegram_id: int, _: bool = Depends(_admin_auth)):
    """Operational view: user settings, martingale step, tokens, affiliate gate line, credential presence."""
    user = await users_repo.get_user(telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    aff = await affiliate_repo.describe_status(telegram_id)
    bal = await tokens_repo.get_balance(telegram_id)
    has_cred = await credentials_repo.has_credentials(telegram_id)
    return {
        "telegram_id": telegram_id,
        "user": user.model_dump(mode="json"),
        "token_balance": bal,
        "affiliate_status": aff,
        "has_credentials": has_cred,
    }


@app.get("/admin/affiliate_account")
async def admin_affiliate_account(email: str, _: bool = Depends(_admin_auth)):
    e = (email or "").strip().lower()
    if not e or "@" not in e:
        raise HTTPException(status_code=400, detail="invalid email")
    doc = await mongo.db.affiliate_accounts.find_one({"email": e})
    if doc is None:
        return {"found": False, "email": e}
    out = dict(doc)
    oid = out.pop("_id", None)
    if oid is not None:
        out["_id"] = str(oid)
    return {"found": True, "email": e, "account": out}


@app.post("/admin/tokens/adjust")
async def admin_tokens_adjust(body: TokenAdjustIn, _: bool = Depends(_admin_auth)):
    if body.delta != 0:
        await tokens_repo.add_tokens(
            body.telegram_id, body.delta, body.reason, {"via": "admin_api"}
        )
    bal = await tokens_repo.get_balance(body.telegram_id)
    return {"ok": True, "telegram_id": body.telegram_id, "balance": bal}


@app.get("/admin/trades")
async def admin_trades(
    _: bool = Depends(_admin_auth),
    limit: int = 50,
    status: str | None = None,
):
    limit = max(1, min(500, int(limit)))
    q: dict = {}
    if status and status.strip():
        q["status"] = status.strip()
    cur = mongo.db.trades.find(q, sort=[("created_at", -1)], limit=limit)
    docs = await cur.to_list(length=limit)
    return {"trades": docs}


@app.get("/admin/signals")
async def admin_signals(_: bool = Depends(_admin_auth), limit: int = 50):
    limit = max(1, min(500, int(limit)))
    cur = mongo.db.signals.find({}, sort=[("created_at", -1)], limit=limit)
    docs = await cur.to_list(length=limit)
    return {"signals": docs}


@app.get("/admin/diagnostics")
async def admin_diagnostics(_: bool = Depends(_admin_auth)):
    s = get_settings()
    mongo_ok = True
    mongo_error = None
    try:
        await mongo.db.command("ping")
    except Exception as e:
        mongo_ok = False
        mongo_error = type(e).__name__

    by_status: dict[str, int] = {}
    try:
        agg = mongo.db.trades.aggregate([{"$group": {"_id": "$status", "c": {"$sum": 1}}}])
        raw = await agg.to_list(length=32)
        for d in raw:
            k = d.get("_id")
            if k is not None:
                by_status[str(k)] = int(d.get("c") or 0)
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    trades_err_24h = 0
    try:
        trades_err_24h = await mongo.db.trades.count_documents(
            {
                "created_at": {"$gte": since_24h},
                "error": {"$exists": True, "$nin": [None, ""]},
            }
        )
    except Exception:
        pass

    counts: dict[str, int] = {}
    try:
        counts["users"] = await mongo.db.users.count_documents({})
        counts["affiliate_accounts"] = await mongo.db.affiliate_accounts.count_documents({})
        counts["credentials_rows"] = await mongo.db.credentials.count_documents({})
        counts["token_balances_nonzero"] = await mongo.db.token_balances.count_documents({"balance": {"$gt": 0}})
        counts["martingale_users"] = await mongo.db.users.count_documents({"settings.martingale_enabled": True})
        counts["token_ledger_24h"] = await mongo.db.token_ledger.count_documents({"created_at": {"$gte": since_24h}})
    except Exception:
        pass

    return {
        "mongodb_ok": mongo_ok,
        "mongodb_error": mongo_error,
        "global_trading_enabled": await system_repo.get_global_trading_enabled(),
        "settlement_worker_running": settlement_worker.running,
        "strategy_worker_running": strategy_worker.running,
        "counts": counts,
        "broker": {
            "pocketoption_place_trade": s.pocketoption_place_trade_enabled(),
            "pocketoption_trade_result": s.pocketoption_trade_result_enabled(),
            "asset_map_configured": bool(s.optional_po_asset_map_json()),
            "trade_otc_only": s.trade_otc_only,
            "trade_min_payout_floor_percent": s.trade_min_payout_floor_percent,
        },
        "trades_by_status": by_status,
        "trades_with_error_last_24h": trades_err_24h,
        "log_level": s.log_level,
        "affiliate_gate_required": s.affiliate_gate_required,
        "affiliate_email_confirm_required": s.affiliate_email_confirm_required,
        "token_system_enabled": s.token_system_enabled,
        "tokens_per_trade": s.tokens_per_trade,
    }


@app.get("/admin/stats")
async def admin_stats(_: bool = Depends(_admin_auth)):
    now = datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    users = await mongo.db.users.count_documents({})
    trades_today = await mongo.db.trades.count_documents({"created_at": {"$gte": day_start}})
    signals_today = await mongo.db.signals.count_documents({"created_at": {"$gte": day_start}})
    return {"users": users, "trades_today": trades_today, "signals_today": signals_today}

