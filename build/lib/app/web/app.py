from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException

from app.config import get_settings
from app.db.mongo import mongo
from app.domain.execution import WebhookSignalIn
from app.repo.signals import signals_repo
from app.repo.system import system_repo
from app.repo.users import users_repo
from app.services.trade_engine import trade_engine


app = FastAPI()


async def _admin_auth(x_api_key: str | None = Header(default=None)) -> bool:
    key = get_settings().require_admin_api_key()
    if not x_api_key or x_api_key != key:
        raise HTTPException(status_code=401, detail="unauthorized")
    return True


@app.on_event("startup")
async def _startup():
    await mongo.connect()


@app.on_event("shutdown")
async def _shutdown():
    await mongo.close()


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/webhook")
async def webhook(signal: WebhookSignalIn):
    created, stored = await signals_repo.store(signal)
    if not created:
        return {"status": "duplicate", "signal": stored.model_dump()}
    try:
        result = await trade_engine.on_signal(stored)
        return {"status": "accepted", "signal": stored.model_dump(), "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=type(e).__name__)


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


@app.get("/admin/trades")
async def admin_trades(_: bool = Depends(_admin_auth), limit: int = 50):
    limit = max(1, min(500, int(limit)))
    cur = mongo.db.trades.find({}, sort=[("created_at", -1)], limit=limit)
    docs = await cur.to_list(length=limit)
    return {"trades": docs}


@app.get("/admin/stats")
async def admin_stats(_: bool = Depends(_admin_auth)):
    now = datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    users = await mongo.db.users.count_documents({})
    trades_today = await mongo.db.trades.count_documents({"created_at": {"$gte": day_start}})
    signals_today = await mongo.db.signals.count_documents({"created_at": {"$gte": day_start}})
    return {"users": users, "trades_today": trades_today, "signals_today": signals_today}

