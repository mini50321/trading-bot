from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.db.mongo import mongo


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TokensRepo:
    async def get_balance(self, telegram_id: int) -> int:
        doc = await mongo.db.token_balances.find_one({"telegram_id": int(telegram_id)})
        return int((doc or {}).get("balance") or 0)

    async def add_tokens(
        self,
        telegram_id: int,
        delta: int,
        reason: str,
        meta: dict[str, Any] | None = None,
        *,
        dedupe_key: str | None = None,
    ) -> bool:
        if delta == 0:
            return True
        entry: dict[str, Any] = {
            "telegram_id": int(telegram_id),
            "delta": int(delta),
            "reason": reason,
            "meta": meta or {},
            "created_at": _now(),
        }
        if dedupe_key:
            entry["dedupe_key"] = dedupe_key
        try:
            await mongo.db.token_ledger.insert_one(entry)
        except DuplicateKeyError:
            if dedupe_key:
                return False
            raise

        await mongo.db.token_balances.update_one(
            {"telegram_id": int(telegram_id)},
            {
                "$inc": {"balance": int(delta)},
                "$set": {"updated_at": _now()},
                "$setOnInsert": {"telegram_id": int(telegram_id), "created_at": _now()},
            },
            upsert=True,
        )
        return True

    async def try_consume(self, telegram_id: int, amount: int) -> bool:
        if amount <= 0:
            return True
        doc = await mongo.db.token_balances.find_one_and_update(
            {"telegram_id": int(telegram_id), "balance": {"$gte": int(amount)}},
            {
                "$inc": {"balance": -int(amount)},
                "$set": {"updated_at": _now()},
                "$setOnInsert": {"telegram_id": int(telegram_id), "created_at": _now()},
            },
            return_document=ReturnDocument.AFTER,
            upsert=False,
        )
        if doc is None:
            return False
        await mongo.db.token_ledger.insert_one(
            {
                "telegram_id": int(telegram_id),
                "delta": -int(amount),
                "reason": "trade_consume",
                "meta": {},
                "created_at": _now(),
            }
        )
        return True


tokens_repo = TokensRepo()
