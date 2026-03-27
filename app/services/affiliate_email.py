from __future__ import annotations

from typing import Any


def detect_email_confirmation(event_label: str, payload: dict[str, Any], patterns: list[str]) -> bool:
    """
    True when the affiliate postback indicates the user's email was confirmed.
    Matches case-insensitive substrings on the normalized event label, plus common boolean fields.
    """
    el = (event_label or "").lower().strip()
    for p in patterns:
        pl = (p or "").strip().lower()
        if pl and pl in el:
            return True

    for key in ("email_confirmed", "email_verified", "is_email_confirmed"):
        v = payload.get(key)
        if v is True:
            return True
        if v is not None and str(v).strip().lower() in ("1", "true", "yes", "confirmed"):
            return True

    return False
