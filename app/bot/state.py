from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SettingsFlow(StatesGroup):
    stake = State()
    expiry = State()
    assets = State()
    max_trades_per_day = State()
    max_loss_per_day = State()
    cooldown_seconds = State()
    max_consecutive_losses = State()


class ConnectFlow(StatesGroup):
    email = State()
    password = State()

