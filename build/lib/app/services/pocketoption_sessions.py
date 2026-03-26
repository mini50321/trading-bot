from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from app.integrations.pocketoption.client import PocketOptionClient, PocketOptionSession
from app.integrations.pocketoption.errors import PocketOptionHttpError
from app.integrations.pocketoption.http import HttpClient
from app.repo.credentials import credentials_repo

T = TypeVar("T")


@dataclass
class _CachedSession:
    session: PocketOptionSession


class PocketOptionSessionManager:
    """
    - Per-user lock to avoid concurrent re-logins.
    - In-memory session cache to reduce DB reads.
    - One retry on 401/403 by forcing a relogin.
    """

    def __init__(self) -> None:
        self._http = HttpClient()
        self._client = PocketOptionClient(self._http)
        self._cache: dict[int, _CachedSession] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._trade_locks: dict[int, asyncio.Lock] = {}
        self._trade_locks_guard = asyncio.Lock()

    async def start(self) -> None:
        await self._http.start()

    async def close(self) -> None:
        await self._http.close()
        self._cache.clear()

    async def _lock_for(self, telegram_id: int) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(telegram_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[telegram_id] = lock
            return lock

    async def trade_lock(self, telegram_id: int) -> asyncio.Lock:
        async with self._trade_locks_guard:
            lock = self._trade_locks.get(telegram_id)
            if lock is None:
                lock = asyncio.Lock()
                self._trade_locks[telegram_id] = lock
            return lock

    async def _login_for_user(self, telegram_id: int) -> PocketOptionSession:
        creds = await credentials_repo.get_credentials(telegram_id)
        if creds is None:
            raise RuntimeError("no credentials")
        email, password = creds
        session = await self._client.login(email, password)
        await credentials_repo.save_session(telegram_id, session.cookies, session.headers)
        self._cache[telegram_id] = _CachedSession(session=session)
        return session

    async def get_or_login(self, telegram_id: int) -> PocketOptionSession:
        cached = self._cache.get(telegram_id)
        if cached is not None:
            return cached.session

        lock = await self._lock_for(telegram_id)
        async with lock:
            cached2 = self._cache.get(telegram_id)
            if cached2 is not None:
                return cached2.session

            existing = await credentials_repo.get_session(telegram_id)
            if existing is not None:
                cookies, headers = existing
                session = PocketOptionSession(cookies=cookies, headers=headers)
                self._cache[telegram_id] = _CachedSession(session=session)
                return session

            return await self._login_for_user(telegram_id)

    async def force_relogin(self, telegram_id: int) -> PocketOptionSession:
        lock = await self._lock_for(telegram_id)
        async with lock:
            return await self._login_for_user(telegram_id)

    async def call(
        self,
        telegram_id: int,
        fn: Callable[[PocketOptionClient, PocketOptionSession], Awaitable[T]],
        *,
        retry_on_auth_failure: bool = True,
    ) -> T:
        session = await self.get_or_login(telegram_id)
        try:
            return await fn(self._client, session)
        except PocketOptionHttpError as e:
            if retry_on_auth_failure and e.status in (401, 403):
                session2 = await self.force_relogin(telegram_id)
                return await fn(self._client, session2)
            raise


pocketoption_sessions = PocketOptionSessionManager()

