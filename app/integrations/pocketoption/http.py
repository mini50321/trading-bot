from __future__ import annotations

from dataclasses import dataclass

import aiohttp


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


class HttpClient:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is not None:
            return
        timeout = aiohttp.ClientTimeout(total=20)
        self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
        self._session = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict | None = None,
        data: dict | None = None,
        cookies: dict[str, str] | None = None,
    ) -> HttpResponse:
        if self._session is None:
            raise RuntimeError("http client not started")
        async with self._session.request(
            method,
            url,
            headers=headers,
            json=json,
            data=data,
            cookies=cookies,
        ) as resp:
            body = await resp.read()
            return HttpResponse(status=resp.status, headers=dict(resp.headers), body=body)

