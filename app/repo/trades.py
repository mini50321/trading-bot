from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

from app.db.mongo import mongo
from app.domain.execution import Trade


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TradesRepo:
    async def create(self, t: Trade) -> None:
        await mongo.db.trades.insert_one(t.model_dump())

    async def update(self, trade_id: str, patch: dict[str, Any]) -> None:
        await mongo.db.trades.update_one({"trade_id": trade_id}, {"$set": patch})

    async def list_recent_for_user(self, telegram_id: int, limit: int = 20) -> list[Trade]:
        cur = mongo.db.trades.find({"telegram_id": telegram_id}, sort=[("created_at", -1)], limit=limit)
        docs = await cur.to_list(length=limit)
        return [Trade.model_validate(d) for d in docs]

    async def stats_since(self, telegram_id: int, since: datetime) -> tuple[int, float]:
        pipeline = [
            {"$match": {"telegram_id": telegram_id, "created_at": {"$gte": since}, "status": "settled"}},
            {"$group": {"_id": None, "count": {"$sum": 1}, "pnl": {"$sum": "$pnl"}}},
        ]
        res = await mongo.db.trades.aggregate(pipeline).to_list(length=1)
        if not res:
            return 0, 0.0
        return int(res[0].get("count") or 0), float(res[0].get("pnl") or 0.0)

    async def sum_stake_since(self, telegram_id: int, since: datetime) -> float:
        pipeline = [
            {"$match": {"telegram_id": telegram_id, "created_at": {"$gte": since}}},
            {"$group": {"_id": None, "total": {"$sum": "$stake"}}},
        ]
        res = await mongo.db.trades.aggregate(pipeline).to_list(length=1)
        if not res:
            return 0.0
        return float(res[0].get("total") or 0.0)

    async def last_settled_results(self, telegram_id: int, limit: int) -> list[float]:
        if limit <= 0:
            return []
        cur = mongo.db.trades.find(
            {"telegram_id": telegram_id, "status": "settled"},
            sort=[("created_at", -1)],
            limit=limit,
            projection={"pnl": 1},
        )
        docs = await cur.to_list(length=limit)
        out = []
        for d in docs:
            try:
                out.append(float(d.get("pnl")))
            except Exception:
                continue
        return out

    async def claim_one_due_for_settlement(self, now: datetime) -> Trade | None:
        candidate = await mongo.db.trades.find_one(
            {"status": {"$in": ["opened", "created"]}, "expiry_at": {"$lte": now}},
            sort=[("expiry_at", 1)],
        )
        if candidate is None:
            return None
        tid = str(candidate.get("trade_id") or "")
        if not tid:
            return None
        updated = await mongo.db.trades.find_one_and_update(
            {"trade_id": tid, "status": {"$in": ["opened", "created"]}},
            {"$set": {"status": "settling"}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return None
        return Trade.model_validate(updated)


trades_repo = TradesRepo()

