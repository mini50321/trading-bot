from __future__ import annotations

from app.integrations.pocketoption.client import PocketOptionSession
from app.services.pocketoption_sessions import pocketoption_sessions


class PocketOptionAuthService:
    async def start(self) -> None:
        await pocketoption_sessions.start()

    async def close(self) -> None:
        await pocketoption_sessions.close()

    async def login_for_user(self, telegram_id: int) -> PocketOptionSession:
        return await pocketoption_sessions.force_relogin(telegram_id)

    async def get_or_login(self, telegram_id: int) -> PocketOptionSession:
        return await pocketoption_sessions.get_or_login(telegram_id)

    async def profile(self, telegram_id: int) -> dict:
        return await pocketoption_sessions.call(telegram_id, lambda c, s: c.profile(s))

    async def balance(self, telegram_id: int) -> dict:
        return await pocketoption_sessions.call(telegram_id, lambda c, s: c.balance(s))


pocketoption_auth = PocketOptionAuthService()

