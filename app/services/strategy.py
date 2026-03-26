from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.market_data import Tick

Direction = Literal["UP", "DOWN"]


@dataclass(frozen=True)
class StrategyDecision:
    symbol: str
    direction: Direction
    reason: str


def momentum_decision(
    *,
    symbol: str,
    ticks: list[Tick],
    min_points: int,
    up_threshold: float,
    down_threshold: float,
) -> StrategyDecision | None:
    sym = (symbol or "").strip().lower()
    if not sym:
        return None
    if min_points <= 1:
        min_points = 2
    if len(ticks) < min_points:
        return None

    start = ticks[-min_points].price
    end = ticks[-1].price
    delta = float(end) - float(start)

    if up_threshold > 0 and delta >= float(up_threshold):
        return StrategyDecision(symbol=sym, direction="UP", reason=f"momentum+{delta}")
    if down_threshold > 0 and delta <= -float(down_threshold):
        return StrategyDecision(symbol=sym, direction="DOWN", reason=f"momentum{delta}")
    return None

