from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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


trades_repo = TradesRepo()

