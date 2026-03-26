from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class SettingsFlow(StatesGroup):
    stake = State()
    expiry = State()
    assets = State()
    min_payout_percent = State()
    max_stake_per_trade = State()
    max_stake_per_day = State()
    max_trades_per_day = State()
    max_loss_per_day = State()
    cooldown_seconds = State()
    max_consecutive_losses = State()


class ConnectFlow(StatesGroup):
    email = State()
    password = State()

