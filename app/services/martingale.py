from __future__ import annotations

from app.domain.types import User, UserSettings


def multipliers_list(settings: UserSettings) -> list[float]:
    """Return `martingale_max_levels` positive multipliers applied to base stake (step 0 = first)."""
    n = max(1, min(20, int(settings.martingale_max_levels)))
    raw = (settings.martingale_multipliers_csv or "").strip()
    if raw:
        out: list[float] = []
        for part in raw.split(","):
            p = part.strip()
            if not p:
                continue
            try:
                v = float(p)
                if v > 0:
                    out.append(v)
            except ValueError:
                continue
            if len(out) >= n:
                break
        while len(out) < n:
            out.append((out[-1] * 2.0) if out else 1.0)
        return out[:n]
    return [max(1.0, 2.0**i) for i in range(n)]


def effective_stake_for_step(base_stake: float, step: int, settings: UserSettings) -> float:
    mults = multipliers_list(settings)
    if not mults:
        return max(0.0, float(base_stake))
    idx = max(0, min(int(step), len(mults) - 1))
    return max(0.0, float(base_stake)) * float(mults[idx])


def stake_for_trade(user: User) -> float:
    base = float(user.settings.stake)
    if not user.settings.martingale_enabled:
        return max(0.0, base)
    return effective_stake_for_step(base, user.martingale_step, user.settings)
