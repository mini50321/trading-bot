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
