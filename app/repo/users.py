from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.mongo import mongo
from app.domain.types import Event, User, UserSettings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UsersRepo:
    async def ensure_user(self, telegram_id: int, username: str | None, first_name: str | None) -> User:
        doc = await mongo.db.users.find_one({"telegram_id": telegram_id})
        if doc is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                created_at=_now(),
                blocked=False,
                settings=UserSettings(),
            )
            await mongo.db.users.insert_one(user.model_dump())
            await self._event(
                "user_created",
                telegram_id,
                {"username": username, "first_name": first_name},
            )
            return user

        if doc.get("username") != username or doc.get("first_name") != first_name:
            await mongo.db.users.update_one(
                {"telegram_id": telegram_id},
                {"$set": {"username": username, "first_name": first_name}},
            )
            await self._event("user_updated", telegram_id, {"username": username, "first_name": first_name})

        return User.model_validate(doc)

    async def get_user(self, telegram_id: int) -> User | None:
        doc = await mongo.db.users.find_one({"telegram_id": telegram_id})
        if doc is None:
            return None
        return User.model_validate(doc)

    async def set_blocked(self, telegram_id: int, blocked: bool) -> bool:
        res = await mongo.db.users.update_one({"telegram_id": telegram_id}, {"$set": {"blocked": blocked}})
        if res.matched_count == 0:
            return False
        await self._event("user_blocked" if blocked else "user_unblocked", telegram_id, {})
        return True

    async def update_settings(self, telegram_id: int, patch: dict[str, Any]) -> User | None:
        user = await self.get_user(telegram_id)
        if user is None:
            return None
        settings = user.settings.model_copy(update=patch)
        await mongo.db.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"settings": settings.model_dump()}},
        )
        await self._event("settings_updated", telegram_id, patch)
        return await self.get_user(telegram_id)

    async def set_martingale_step(self, telegram_id: int, step: int) -> None:
        step = max(0, int(step))
        await mongo.db.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"martingale_step": step}},
        )

    async def set_trading_enabled(self, telegram_id: int, enabled: bool) -> bool:
        res = await mongo.db.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"settings.trading_enabled": enabled}},
        )
        if res.matched_count == 0:
            return False
        await self._event("trading_enabled" if enabled else "trading_disabled", telegram_id, {})
        return True

    async def list_users(self, limit: int = 50) -> list[User]:
        cur = mongo.db.users.find({}, sort=[("created_at", -1)], limit=limit)
        docs = await cur.to_list(length=limit)
        return [User.model_validate(d) for d in docs]

    async def _event(self, type_: str, telegram_id: int, payload: dict[str, Any]) -> None:
        event = Event(type=type_, telegram_id=telegram_id, created_at=_now(), payload=payload)
        await mongo.db.events.insert_one(event.model_dump())


users_repo = UsersRepo()

