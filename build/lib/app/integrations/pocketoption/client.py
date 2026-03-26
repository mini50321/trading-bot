from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.integrations.pocketoption.http import HttpClient


@dataclass(frozen=True)
class PocketOptionSession:
    cookies: dict[str, str]
    headers: dict[str, str]


class PocketOptionClient:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def _url(self, path: str) -> str:
        settings = get_settings()
        base = settings.po_api_base_url.rstrip("/")
        p = path.strip()
        if not base or not p:
            raise ValueError("pocketoption api base url and paths must be configured")
        if not p.startswith("/"):
            p = "/" + p
        return base + p

    async def login(self, email: str, password: str) -> PocketOptionSession:
        settings = get_settings()
        url = self._url(settings.po_login_path)
        resp = await self._http.request("POST", url, json={"email": email, "password": password})
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"login failed: {resp.status}")
        cookies: dict[str, str] = {}
        set_cookie = resp.headers.get("Set-Cookie")
        if set_cookie:
            parts = set_cookie.split(";")
            if parts and "=" in parts[0]:
                k, v = parts[0].split("=", 1)
                cookies[k.strip()] = v.strip()
        headers = {"Content-Type": "application/json"}
        return PocketOptionSession(cookies=cookies, headers=headers)

    async def profile(self, session: PocketOptionSession) -> dict[str, Any]:
        settings = get_settings()
        url = self._url(settings.po_profile_path)
        resp = await self._http.request("GET", url, headers=session.headers, cookies=session.cookies)
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"profile failed: {resp.status}")
        return json.loads(resp.body.decode("utf-8") or "{}")

    async def balance(self, session: PocketOptionSession) -> dict[str, Any]:
        settings = get_settings()
        url = self._url(settings.po_balance_path)
        resp = await self._http.request("GET", url, headers=session.headers, cookies=session.cookies)
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"balance failed: {resp.status}")
        return json.loads(resp.body.decode("utf-8") or "{}")

