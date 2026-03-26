from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class WebhookSignalIn(BaseModel):
    source: str = Field(default="webhook", min_length=1, max_length=80)
    signal_id: str = Field(min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=50)
    direction: Literal["UP", "DOWN"]
    created_at: datetime | None = None
    payload: dict = Field(default_factory=dict)

    @field_validator("source", "signal_id")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return (v or "").strip().lower()

    @field_validator("payload", mode="before")
    @classmethod
    def payload_must_be_dict(cls, v: object) -> dict:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise ValueError("payload must be an object")
        return v


class StoredSignal(BaseModel):
    source: str
    signal_id: str
    symbol: str
    direction: Literal["UP", "DOWN"]
    created_at: datetime
    payload: dict = Field(default_factory=dict)


class Trade(BaseModel):
    trade_id: str
    telegram_id: int
    broker: Literal["simulated", "pocketoption"] = "simulated"
    broker_trade_id: str | None = None
    symbol: str
    direction: Literal["UP", "DOWN"]
    stake: float
    expiry_seconds: int
    placed_at: datetime | None = None
    expiry_at: datetime | None = None
    entry_price: float | None = None
    entry_ts: float | None = None
    exit_price: float | None = None
    exit_ts: float | None = None
    status: Literal["created", "opened", "settling", "settled", "failed"]
    pnl: float | None = None
    win_profit_percent: float | None = None
    loss_percent: float | None = None
    signal_source: str
    signal_id: str
    created_at: datetime
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

