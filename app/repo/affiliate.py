from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.mongo import mongo


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AffiliateRepo:
    async def record_event(self, payload: dict[str, Any]) -> None:
        doc = {"created_at": _now(), "payload": payload}
        await mongo.db.affiliate_events.insert_one(doc)

    async def upsert_account_by_email(self, email: str, patch: dict[str, Any]) -> None:
        e = (email or "").strip().lower()
        if not e:
            return
        await mongo.db.affiliate_accounts.update_one(
            {"email": e},
            {"$set": {"email": e, **patch, "updated_at": _now()}},
            upsert=True,
        )

    async def link_telegram_id(self, email: str, telegram_id: int) -> None:
        e = (email or "").strip().lower()
        if not e:
            return
        await mongo.db.affiliate_accounts.update_one(
            {"email": e},
            {"$set": {"telegram_id": int(telegram_id), "updated_at": _now()}},
            upsert=True,
        )


affiliate_repo = AffiliateRepo()

