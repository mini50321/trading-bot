from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings


class Mongo:
    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        settings = get_settings()
        self._client = AsyncIOMotorClient(settings.mongodb_uri)
        self._db = self._client[settings.mongodb_db]

        await self._db.users.create_index("telegram_id", unique=True)
        await self._db.users.create_index("created_at")
        await self._db.events.create_index("created_at")
        await self._db.credentials.create_index("telegram_id", unique=True)
        await self._db.sessions.create_index("telegram_id", unique=True)
        await self._db.sessions.create_index("updated_at")
        await self._db.signals.create_index([("source", 1), ("signal_id", 1)], unique=True)
        await self._db.signals.create_index("created_at")
        await self._db.trades.create_index("created_at")
        await self._db.trades.create_index([("telegram_id", 1), ("created_at", -1)])
        await self._db.system.create_index("key", unique=True)
        await self._db.affiliate_events.create_index("created_at")
        await self._db.affiliate_accounts.create_index("email", unique=True)
        await self._db.affiliate_accounts.create_index("telegram_id")

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None
        self._db = None

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("mongo not connected")
        return self._db


mongo = Mongo()

