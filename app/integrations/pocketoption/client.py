from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

from app.config import get_settings
from app.integrations.pocketoption.errors import PocketOptionHttpError
from app.integrations.pocketoption.http import HttpClient
from app.integrations.pocketoption.jsonpath import get_by_dotted_path


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
            raise PocketOptionHttpError(op="login", status=resp.status, body=resp.body)
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
            raise PocketOptionHttpError(op="profile", status=resp.status, body=resp.body)
        return json.loads(resp.body.decode("utf-8") or "{}")

    async def balance(self, session: PocketOptionSession) -> dict[str, Any]:
        settings = get_settings()
        url = self._url(settings.po_balance_path)
        resp = await self._http.request("GET", url, headers=session.headers, cookies=session.cookies)
        if resp.status < 200 or resp.status >= 300:
            raise PocketOptionHttpError(op="balance", status=resp.status, body=resp.body)
        return json.loads(resp.body.decode("utf-8") or "{}")

    async def place_trade(
        self,
        session: PocketOptionSession,
        *,
        asset_id: str,
        amount: float,
        direction: Literal["UP", "DOWN"],
        expiry_seconds: int,
    ) -> tuple[dict[str, Any], str | None]:
        settings = get_settings()
        path = settings.po_place_trade_path.strip()
        if not path:
            raise ValueError("PO_PLACE_TRADE_PATH is not configured")

        dir_val = (
            settings.po_trade_direction_up if direction == "UP" else settings.po_trade_direction_down
        )
        body: dict[str, Any] = {
            settings.po_trade_field_asset_id.strip() or "asset_id": asset_id,
            settings.po_trade_field_amount.strip() or "amount": amount,
            settings.po_trade_field_direction.strip() or "direction": dir_val,
            settings.po_trade_field_expiry.strip() or "expiry_seconds": int(expiry_seconds),
        }

        extra_raw = settings.po_trade_body_extra_json.strip()
        if extra_raw:
            try:
                extra = json.loads(extra_raw)
                if isinstance(extra, dict):
                    body = {**extra, **body}
            except Exception:
                pass

        url = self._url(path)
        resp = await self._http.request("POST", url, headers=session.headers, cookies=session.cookies, json=body)
        parsed: dict[str, Any]
        try:
            parsed = json.loads(resp.body.decode("utf-8") or "{}")
        except Exception:
            parsed = {}

        if resp.status < 200 or resp.status >= 300:
            raise PocketOptionHttpError(op="place_trade", status=resp.status, body=resp.body)

        broker_id: str | None = None
        id_path = settings.po_trade_response_broker_id_path.strip()
        if id_path:
            raw = get_by_dotted_path(parsed, id_path)
            if raw is not None and str(raw).strip():
                broker_id = str(raw).strip()

        return parsed, broker_id

    async def trade_result(self, session: PocketOptionSession, broker_trade_id: str) -> dict[str, Any]:
        settings = get_settings()
        tmpl = settings.po_trade_result_path_template.strip()
        if not tmpl or "{id}" not in tmpl:
            raise ValueError("PO_TRADE_RESULT_PATH_TEMPLATE must contain {id}")
        safe_id = quote(str(broker_trade_id), safe="")
        path = tmpl.replace("{id}", safe_id)
        url = self._url(path)
        method = (settings.po_trade_result_http_method or "GET").strip().upper()
        if method == "POST":
            body = None
            post_raw = settings.po_trade_result_post_json.strip()
            if post_raw:
                try:
                    body = json.loads(post_raw.replace("{id}", safe_id))
                except Exception:
                    body = None
            resp = await self._http.request(
                "POST", url, headers=session.headers, cookies=session.cookies, json=body
            )
        else:
            resp = await self._http.request("GET", url, headers=session.headers, cookies=session.cookies)
        try:
            parsed = json.loads(resp.body.decode("utf-8") or "{}")
        except Exception:
            parsed = {}
        if resp.status < 200 or resp.status >= 300:
            raise PocketOptionHttpError(op="trade_result", status=resp.status, body=resp.body)
        if not isinstance(parsed, dict):
            return {}
        return parsed

