from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu(trading_enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="settings", callback_data="menu:settings"),
                InlineKeyboardButton(text="status", callback_data="menu:status"),
            ],
            [
                InlineKeyboardButton(
                    text=("disable trading" if trading_enabled else "enable trading"),
                    callback_data=("trade:disable" if trading_enabled else "trade:enable"),
                )
            ],
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="set stake", callback_data="set:stake"),
                InlineKeyboardButton(text="set expiry", callback_data="set:expiry"),
            ],
            [
                InlineKeyboardButton(text="martingale on/off", callback_data="set:martingale_enabled"),
                InlineKeyboardButton(text="mg levels (1-20)", callback_data="set:martingale_max_levels"),
            ],
            [
                InlineKeyboardButton(text="mg multipliers csv", callback_data="set:martingale_multipliers"),
            ],
            [
                InlineKeyboardButton(text="set assets", callback_data="set:assets"),
            ],
            [
                InlineKeyboardButton(text="strategy on/off", callback_data="set:strategy_enabled"),
            ],
            [
                InlineKeyboardButton(text="min payout %", callback_data="set:min_payout_percent"),
                InlineKeyboardButton(text="max stake/trade", callback_data="set:max_stake_per_trade"),
            ],
            [
                InlineKeyboardButton(text="max stake/day", callback_data="set:max_stake_per_day"),
            ],
            [
                InlineKeyboardButton(text="max trades/day", callback_data="set:max_trades_per_day"),
                InlineKeyboardButton(text="max loss/day", callback_data="set:max_loss_per_day"),
            ],
            [
                InlineKeyboardButton(text="cooldown", callback_data="set:cooldown_seconds"),
                InlineKeyboardButton(text="loss streak", callback_data="set:max_consecutive_losses"),
            ],
            [
                InlineKeyboardButton(text="back", callback_data="menu:back"),
            ],
        ]
    )

