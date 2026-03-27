from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import HTTPException

from app.domain.execution import WebhookSignalIn
from app.web.webhook_guard import parse_webhook_json, verify_webhook_hmac_sha256


def test_webhook_signal_normalizes_and_validates_payload() -> None:
    s = WebhookSignalIn.model_validate(
        {
            "signal_id": "sig-001",
            "symbol": " EURUSD ",
            "direction": "UP",
            "payload": {"stake": 10.5, "expiry_seconds": 30},
        }
    )
    assert s.symbol == "eurusd"
    assert s.direction == "UP"
    assert s.payload["stake"] == 10.5


def test_webhook_signal_rejects_non_object_payload() -> None:
    with pytest.raises(ValueError):
        WebhookSignalIn.model_validate(
            {
                "signal_id": "x",
                "symbol": "eurusd",
                "direction": "DOWN",
                "payload": [],
            }
        )


def test_parse_webhook_json_accepts_object() -> None:
    assert parse_webhook_json(b' {"a": 1} ') == {"a": 1}


def test_parse_webhook_json_rejects_empty() -> None:
    with pytest.raises(HTTPException) as ei:
        parse_webhook_json(b"   ")
    assert ei.value.status_code == 400


def test_parse_webhook_json_rejects_non_object() -> None:
    with pytest.raises(HTTPException) as ei:
        parse_webhook_json(b"[1,2,3]")
    assert ei.value.status_code == 400


def test_hmac_signature_roundtrip() -> None:
    secret = "test-secret"
    body = b'{"signal_id":"1","symbol":"eurusd","direction":"UP"}'
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert verify_webhook_hmac_sha256(
        secret=secret, body=body, signature_header=f"sha256={digest}"
    )
    assert verify_webhook_hmac_sha256(secret=secret, body=body, signature_header=digest)


def test_observability_log_event_does_not_raise() -> None:
    from app.observability.log import log_event, log_warning

    log_event("smoke.test", foo="bar", n=1)
    log_warning("smoke.warn", x=True)


def test_detect_email_confirmation_event_label() -> None:
    from app.services.affiliate_email import detect_email_confirmation

    pats = ["email confirmation", "email_confirmation"]
    assert detect_email_confirmation("Email Confirmation", {}, pats)
    assert detect_email_confirmation("foo_email_confirmation_bar", {}, pats)
    assert not detect_email_confirmation("registration", {}, pats)


def test_detect_email_confirmation_payload_flags() -> None:
    from app.services.affiliate_email import detect_email_confirmation

    assert detect_email_confirmation("", {"email_confirmed": True}, [])
    assert detect_email_confirmation("", {"email_verified": "yes"}, [])
    assert not detect_email_confirmation("", {"email_confirmed": False}, [])


def test_is_tradable_otc_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import assets as assets_mod

    class S:
        trade_otc_only = True
        optional_po_asset_map_json = staticmethod(
            lambda: '{"good":{"id":"1","otc":true,"payout":92},"bad":{"id":"2","otc":false,"payout":92},"bare":"3"}'
        )

    monkeypatch.setattr(assets_mod, "get_settings", lambda: S())
    cat = assets_mod.AssetCatalog()
    assert cat.is_tradable("good", min_payout_percent=90.0, require_otc=True)[0]
    assert cat.is_tradable("good", min_payout_percent=93.0, require_otc=True) == (False, "payout_below_threshold")
    assert cat.is_tradable("bad", min_payout_percent=90.0, require_otc=True) == (False, "not_otc")
    assert cat.is_tradable("bare", min_payout_percent=None, require_otc=True) == (False, "otc_unknown")


def test_deposit_token_brackets() -> None:
    from types import SimpleNamespace

    from app.services.token_deposit import deposit_tokens_for_amount

    s = SimpleNamespace(
        token_deposit_min_usd=20.0,
        token_bracket_low_grant=15,
        token_bracket_high_min_usd=100.0,
        token_bracket_high_per_dollar=1.0,
    )
    assert deposit_tokens_for_amount(19, s) == 0
    assert deposit_tokens_for_amount(50, s) == 15
    assert deposit_tokens_for_amount(99, s) == 15
    assert deposit_tokens_for_amount(100, s) == 100
    assert deposit_tokens_for_amount(150, s) == 150
