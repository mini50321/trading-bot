from __future__ import annotations

from datetime import datetime, timezone

from app.db.mongo import mongo


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SystemRepo:
    async def set_global_trading_enabled(self, enabled: bool) -> None:
        await mongo.db.system.update_one(
            {"key": "global_trading_enabled"},
            {"$set": {"key": "global_trading_enabled", "enabled": bool(enabled), "updated_at": _now()}},
            upsert=True,
        )

    async def get_global_trading_enabled(self) -> bool:
        doc = await mongo.db.system.find_one({"key": "global_trading_enabled"})
        if doc is None:
            return True
        return bool(doc.get("enabled", True))


system_repo = SystemRepo()

