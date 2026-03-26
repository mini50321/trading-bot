from __future__ import annotations

from app.integrations.pocketoption.client import PocketOptionClient, PocketOptionSession
from app.integrations.pocketoption.http import HttpClient
from app.repo.credentials import credentials_repo


class PocketOptionAuthService:
    def __init__(self) -> None:
        self._http = HttpClient()
        self._client = PocketOptionClient(self._http)

    async def start(self) -> None:
        await self._http.start()

    async def close(self) -> None:
        await self._http.close()

    async def login_for_user(self, telegram_id: int) -> PocketOptionSession:
        creds = await credentials_repo.get_credentials(telegram_id)
        if creds is None:
            raise RuntimeError("no credentials")
        email, password = creds
        session = await self._client.login(email, password)
        await credentials_repo.save_session(telegram_id, session.cookies, session.headers)
        return session

    async def get_or_login(self, telegram_id: int) -> PocketOptionSession:
        existing = await credentials_repo.get_session(telegram_id)
        if existing is not None:
            cookies, headers = existing
            return PocketOptionSession(cookies=cookies, headers=headers)
        return await self.login_for_user(telegram_id)

    async def profile(self, telegram_id: int) -> dict:
        session = await self.get_or_login(telegram_id)
        return await self._client.profile(session)

    async def balance(self, telegram_id: int) -> dict:
        session = await self.get_or_login(telegram_id)
        return await self._client.balance(session)


pocketoption_auth = PocketOptionAuthService()

