from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserSettings(BaseModel):
    trading_enabled: bool = False
    stake: float = 1.0
    expiry_seconds: int = 5
    assets: list[str] = Field(default_factory=list)
    max_trades_per_day: int = 50
    max_loss_per_day: float = 0.0
    cooldown_seconds: int = 0
    max_consecutive_losses: int = 0


class User(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    created_at: datetime
    blocked: bool = False
    settings: UserSettings = Field(default_factory=UserSettings)


class Event(BaseModel):
    type: Literal[
        "user_created",
        "user_updated",
        "settings_updated",
        "trading_enabled",
        "trading_disabled",
        "user_blocked",
        "user_unblocked",
    ]
    telegram_id: int
    created_at: datetime
    payload: dict = Field(default_factory=dict)

