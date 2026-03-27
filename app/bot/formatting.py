from __future__ import annotations

from app.domain.types import User


def user_status_text(user: User) -> str:
    s = user.settings
    assets = ", ".join(s.assets) if s.assets else "none"
    enabled = "on" if s.trading_enabled else "off"
    blocked = "yes" if user.blocked else "no"
    mg = "on" if s.martingale_enabled else "off"
    step_line = f"martingale_step: {user.martingale_step}\n" if s.martingale_enabled else ""
    return (
        f"trading: {enabled}\n"
        f"blocked: {blocked}\n"
        f"martingale: {mg} (levels={s.martingale_max_levels})\n"
        f"{step_line}"
        f"stake: {s.stake}\n"
        f"expiry_seconds: {s.expiry_seconds}\n"
        f"assets: {assets}\n"
        f"min_payout_percent: {s.min_payout_percent}\n"
        f"max_stake_per_trade: {s.max_stake_per_trade}\n"
        f"max_stake_per_day: {s.max_stake_per_day}\n"
        f"max_trades_per_day: {s.max_trades_per_day}\n"
        f"max_loss_per_day: {s.max_loss_per_day}\n"
        f"cooldown_seconds: {s.cooldown_seconds}\n"
        f"max_consecutive_losses: {s.max_consecutive_losses}"
    )

