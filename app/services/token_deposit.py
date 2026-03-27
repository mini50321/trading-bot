from __future__ import annotations

import re
from typing import Any

from app.config import Settings


def detect_deposit_postback(event_label: str, payload: dict[str, Any], patterns: list[str]) -> bool:
    el = (event_label or "").lower().strip()
    for p in patterns:
        pl = (p or "").strip().lower()
        if pl and pl in el:
            return True
    for key in ("is_deposit", "deposit", "first_deposit"):
        v = payload.get(key)
        if v is True:
            return True
        if v is not None and str(v).strip().lower() in ("1", "true", "yes", "first", "redeposit"):
            return True
    return False


def parse_deposit_amount_usd(payload: dict[str, Any]) -> float | None:
    """Best-effort USD deposit amount from common affiliate macro keys."""
    keys = (
        "amount",
        "deposit",
        "deposit_amount",
        "sum",
        "value",
        "usd",
        "money",
        "payment_amount",
        "deposit_sum",
    )
    for key in keys:
        raw = payload.get(key)
        if raw is None or raw == "":
            continue
        v = _coerce_amount(raw)
        if v is not None and v > 0:
            return v
    return None


def _coerce_amount(raw: Any) -> float | None:
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def deposit_tokens_for_amount(amount_usd: float, s: Settings) -> int:
    if amount_usd < float(s.token_deposit_min_usd):
        return 0
    hi = float(s.token_bracket_high_min_usd)
    if amount_usd >= hi:
        return int(amount_usd * float(s.token_bracket_high_per_dollar))
    return int(s.token_bracket_low_grant)


def deposit_dedupe_key(email: str, event_label: str, payload: dict[str, Any]) -> str | None:
    e = (email or "").strip().lower()
    for k in ("transaction_id", "tid", "deposit_id", "order_id", "payment_id", "tr_id"):
        v = payload.get(k)
        if v is not None and str(v).strip():
            return f"{e}:{k}:{str(v).strip()}"
    return None
