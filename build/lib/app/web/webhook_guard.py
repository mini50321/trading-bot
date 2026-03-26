from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def extract_client_ip(request: Request, *, trust_x_forwarded_for: bool) -> str:
    if trust_x_forwarded_for:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host
    return "unknown"


def verify_webhook_hmac_sha256(*, secret: str, body: bytes, signature_header: str | None) -> bool:
    if not secret or signature_header is None or not signature_header.strip():
        return False
    s = signature_header.strip()
    if s.lower().startswith("sha256="):
        sig_hex = s.split("=", 1)[1].strip()
    else:
        sig_hex = s.strip()
    try:
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    except Exception:
        return False
    if len(sig_hex) != len(expected):
        return False
    try:
        return hmac.compare_digest(expected, sig_hex.lower())
    except Exception:
        return False


def parse_webhook_json(body: bytes) -> dict:
    try:
        text = body.decode("utf-8")
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid_body_encoding") from e
    if not text.strip():
        raise HTTPException(status_code=400, detail="empty_body")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="invalid_json") from e
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="json_must_be_object")
    return data


class WebhookRateLimiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str, *, limit: int, window_sec: float = 60.0) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        async with self._lock:
            dq = self._hits[key]
            while dq and dq[0] < now - window_sec:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True


webhook_rate_limiter = WebhookRateLimiter()
