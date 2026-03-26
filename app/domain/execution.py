from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WebhookSignalIn(BaseModel):
    source: str = "webhook"
    signal_id: str = Field(min_length=1, max_length=200)
    symbol: str = Field(min_length=1, max_length=50)
    direction: Literal["UP", "DOWN"]
    created_at: datetime | None = None
    payload: dict = Field(default_factory=dict)


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
    symbol: str
    direction: Literal["UP", "DOWN"]
    stake: float
    expiry_seconds: int
    entry_price: float | None = None
    entry_ts: float | None = None
    exit_price: float | None = None
    exit_ts: float | None = None
    status: Literal["created", "opened", "settled", "failed"]
    pnl: float | None = None
    win_profit_percent: float | None = None
    loss_percent: float | None = None
    signal_source: str
    signal_id: str
    created_at: datetime
    error: str | None = None

