from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from app.services.market_data import Tick


Direction = Literal["UP", "DOWN"]


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class SignalStrength(Enum):
    STRONG_BUY = ("STRONG_BUY", 1.00)
    BUY = ("BUY", 0.75)
    NEUTRAL = ("NEUTRAL", 0.50)
    SELL = ("SELL", 0.25)
    STRONG_SELL = ("STRONG_SELL", 0.00)

    def __init__(self, label: str, score: float):
        self.label = label
        self.score = score


@dataclass
class Signal:
    direction: Direction | None
    confidence: float
    strength: SignalStrength
    reasons: list[str] = field(default_factory=list)
    confluence_score: float = 0.0
    market_regime: MarketRegime = MarketRegime.UNKNOWN


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


class MicrostructureAnalyzer:
    """
    Adapted from the provided script, but for mid-only ticks (no bid/ask).
    """

    def __init__(self, *, tick_history_size: int, momentum_window: int, pressure_window: int, ofi_threshold: float):
        self.tick_history_size = int(tick_history_size)
        self.momentum_window = int(momentum_window)
        self.pressure_window = int(pressure_window)
        self.ofi_threshold = float(ofi_threshold)

        self.mids: list[float] = []
        self.ready = False

        self.ofi = 0.0
        self.momentum = 0.0
        self.momentum_acceleration = 0.0
        self.tick_imbalance = 0.0

    def update_mid(self, mid: float) -> None:
        self.mids.append(float(mid))
        if len(self.mids) > self.tick_history_size:
            self.mids = self.mids[-self.tick_history_size :]

        need = max(self.momentum_window, self.pressure_window) + 5
        if len(self.mids) >= need:
            self.ready = True
            self._calc_ofi()
            self._calc_momentum()
            self._calc_tick_imbalance()

    def _calc_ofi(self) -> None:
        w = self.mids[-self.pressure_window :]
        score = 0.0
        total = 0.0
        for i in range(1, len(w)):
            d = w[i] - w[i - 1]
            if d > 0:
                score += 1
            elif d < 0:
                score -= 1
            total += 1
        self.ofi = score / total if total else 0.0

    def _calc_momentum(self) -> None:
        w = self.mids[-self.momentum_window :]
        if len(w) < 3:
            self.momentum = 0.0
            self.momentum_acceleration = 0.0
            return
        diffs = [w[i] - w[i - 1] for i in range(1, len(w))]
        self.momentum = statistics.mean(diffs) if diffs else 0.0
        if len(diffs) >= 2:
            self.momentum_acceleration = statistics.mean([diffs[i] - diffs[i - 1] for i in range(1, len(diffs))])
        else:
            self.momentum_acceleration = 0.0

    def _calc_tick_imbalance(self) -> None:
        w = self.mids[-self.momentum_window :]
        up = 0
        dn = 0
        for i in range(1, len(w)):
            if w[i] > w[i - 1]:
                up += 1
            elif w[i] < w[i - 1]:
                dn += 1
        tot = up + dn
        self.tick_imbalance = (up - dn) / tot if tot else 0.0

    def contribution(self) -> tuple[float, float, list[str]]:
        if not self.ready:
            return 0.0, 0.0, ["Not ready"]

        up = 0.0
        dn = 0.0
        reasons: list[str] = []

        if self.ofi > self.ofi_threshold:
            up += 0.30 * abs(self.ofi)
            reasons.append(f"OFI_BULL({self.ofi:+.3f})")
        elif self.ofi < -self.ofi_threshold:
            dn += 0.30 * abs(self.ofi)
            reasons.append(f"OFI_BEAR({self.ofi:+.3f})")

        if self.momentum > 0 and self.momentum_acceleration > 0:
            up += 0.25 * (1 + self.momentum_acceleration * 100)
            reasons.append(f"MOM_UP({self.momentum:+.2e})")
        elif self.momentum < 0 and self.momentum_acceleration < 0:
            dn += 0.25 * (1 + abs(self.momentum_acceleration) * 100)
            reasons.append(f"MOM_DN({self.momentum:+.2e})")

        if self.tick_imbalance > 0.30:
            up += 0.20 * abs(self.tick_imbalance)
            reasons.append(f"TI_UP({self.tick_imbalance:+.3f})")
        elif self.tick_imbalance < -0.30:
            dn += 0.20 * abs(self.tick_imbalance)
            reasons.append(f"TI_DN({self.tick_imbalance:+.3f})")

        return up, dn, reasons


class RegimeDetector:
    def __init__(self, *, volatility_lookback: int, trend_detection_period: int):
        self.volatility_lookback = int(volatility_lookback)
        self.trend_detection_period = int(trend_detection_period)
        self.prices: list[float] = []
        self.regime: MarketRegime = MarketRegime.UNKNOWN

    def update(self, price: float) -> None:
        self.prices.append(float(price))
        maxlen = self.volatility_lookback * 2
        if len(self.prices) > maxlen:
            self.prices = self.prices[-maxlen:]
        if len(self.prices) >= self.volatility_lookback:
            self._detect()

    def _detect(self) -> None:
        prices = self.prices
        returns = []
        for i in range(1, len(prices)):
            p0 = prices[i - 1]
            if p0:
                returns.append((prices[i] - p0) / p0)
        vol = statistics.stdev(returns) if len(returns) > 1 else 0.0

        # slope + r2
        n = len(prices)
        x = list(range(n))
        sx = sum(x)
        sy = sum(prices)
        sxy = sum(x[i] * prices[i] for i in range(n))
        sx2 = sum(xi * xi for xi in x)
        denom = n * sx2 - sx * sx
        slope = (n * sxy - sx * sy) / denom if denom else 0.0
        ym = sy / n if n else 0.0
        ss_tot = sum((y - ym) ** 2 for y in prices)
        b0 = (sy - slope * sx) / n if n else 0.0
        ss_res = sum((prices[i] - (slope * x[i] + b0)) ** 2 for i in range(n))
        r2 = 1 - ss_res / ss_tot if ss_tot else 0.0

        rec = prices[-self.trend_detection_period :] if self.trend_detection_period > 0 else prices
        m = statistics.mean(rec) if rec else 0.0
        rng = (max(rec) - min(rec)) / m if m else 0.0

        if vol > 0.0005:
            self.regime = MarketRegime.VOLATILE
        elif rng < 0.001 and r2 < 0.3:
            self.regime = MarketRegime.RANGING
        elif slope > 0 and r2 > 0.5:
            self.regime = MarketRegime.TRENDING_UP
        elif slope < 0 and r2 > 0.5:
            self.regime = MarketRegime.TRENDING_DOWN
        else:
            self.regime = MarketRegime.UNKNOWN

    def favorable(self, direction: Direction) -> tuple[bool, float]:
        if self.regime == MarketRegime.VOLATILE:
            return False, 0.0
        if self.regime == MarketRegime.RANGING:
            return True, 0.6
        if direction == "UP":
            if self.regime == MarketRegime.TRENDING_UP:
                return True, 0.9
            if self.regime == MarketRegime.TRENDING_DOWN:
                return False, 0.2
        else:
            if self.regime == MarketRegime.TRENDING_DOWN:
                return True, 0.9
            if self.regime == MarketRegime.TRENDING_UP:
                return False, 0.2
        return True, 0.5


class PatternRecognizer:
    def __init__(self) -> None:
        self.prices: list[float] = []

    def update(self, price: float) -> None:
        self.prices.append(float(price))
        if len(self.prices) > 50:
            self.prices = self.prices[-50:]

    def detect(self) -> list[dict]:
        p = self.prices
        out: list[dict] = []
        for fn in (self._pin_bar, self._engulfing, self._doji, self._three_tick):
            r = fn(p)
            if r:
                out.append(r)
        return out

    def _pin_bar(self, p: list[float]):
        if len(p) < 3:
            return None
        p1, p2, p3 = p[-3], p[-2], p[-1]
        if p2 < p1 and p2 < p3 and p3 > p1:
            body = abs(p3 - p2)
            wick = p1 - p2
            if body > 0 and wick > body * 2:
                return {"type": "BULLISH_PIN", "strength": min(1.0, wick / body / 3), "direction": "UP"}
        if p2 > p1 and p2 > p3 and p3 < p1:
            body = abs(p2 - p3)
            wick = p2 - p1
            if body > 0 and wick > body * 2:
                return {"type": "BEARISH_PIN", "strength": min(1.0, wick / body / 3), "direction": "DOWN"}
        return None

    def _engulfing(self, p: list[float]):
        if len(p) < 4:
            return None
        p1, p2, p3, p4 = p[-4], p[-3], p[-2], p[-1]
        if p2 < p1 and p4 > p2 and p4 > p3 and p3 > p2:
            dn = p1 - p2
            up = p4 - p3
            if dn > 0 and up > dn * 0.8:
                return {"type": "BULL_ENGULF", "strength": min(1.0, up / dn), "direction": "UP"}
        if p2 > p1 and p4 < p2 and p4 < p3 and p3 < p2:
            up = p2 - p1
            dn = p3 - p4
            if up > 0 and dn > up * 0.8:
                return {"type": "BEAR_ENGULF", "strength": min(1.0, dn / up), "direction": "DOWN"}
        return None

    def _doji(self, p: list[float]):
        if len(p) < 5:
            return None
        rng = max(p[-5:]) - min(p[-5:])
        if rng == 0:
            return None
        body = abs(p[-1] - p[-2])
        if body < rng * 0.1:
            if p[-3] > p[-4] and p[-2] > p[-3]:
                return {"type": "DOJI_RALLY", "strength": 0.6, "direction": "DOWN"}
            if p[-3] < p[-4] and p[-2] < p[-3]:
                return {"type": "DOJI_DECLINE", "strength": 0.6, "direction": "UP"}
        return None

    def _three_tick(self, p: list[float]):
        if len(p) < 4:
            return None
        p1, p2, p3, p4 = p[-4], p[-3], p[-2], p[-1]
        if p2 < p1 and p3 < p2 and p4 > p3:
            dec = p1 - p3
            reb = p4 - p3
            if dec > 0 and reb > dec * 0.3:
                return {"type": "3TICK_BULL", "strength": min(1.0, reb / dec), "direction": "UP"}
        if p2 > p1 and p3 > p2 and p4 < p3:
            ral = p3 - p1
            dec = p3 - p4
            if ral > 0 and dec > ral * 0.3:
                return {"type": "3TICK_BEAR", "strength": min(1.0, dec / ral), "direction": "DOWN"}
        return None


class LevelAnalyzer:
    def __init__(self) -> None:
        self.prices: list[float] = []
        self.levels: list[dict] = []
        self._tick_count = 0

    def update(self, price: float) -> None:
        self.prices.append(float(price))
        if len(self.prices) > 200:
            self.prices = self.prices[-200:]
        self._tick_count += 1
        if self._tick_count % 50 == 0:
            self._recalc()

    def _recalc(self) -> None:
        p = self.prices
        if len(p) < 50:
            return
        highs: list[float] = []
        lows: list[float] = []
        for i in range(2, len(p) - 2):
            if p[i] > p[i - 1] and p[i] > p[i - 2] and p[i] > p[i + 1] and p[i] > p[i + 2]:
                highs.append(p[i])
            if p[i] < p[i - 1] and p[i] < p[i - 2] and p[i] < p[i + 1] and p[i] < p[i + 2]:
                lows.append(p[i])

        self.levels = []
        for lp, s in self._cluster(highs):
            self.levels.append({"price": lp, "type": "RESISTANCE", "strength": s})
        for lp, s in self._cluster(lows):
            self.levels.append({"price": lp, "type": "SUPPORT", "strength": s})
        self.levels.sort(key=lambda x: x["strength"], reverse=True)

    def _cluster(self, prices: list[float]):
        if not prices:
            return []
        out = []
        used = set()
        for i, p1 in enumerate(prices):
            if i in used:
                continue
            cl = [p1]
            used.add(i)
            for j in range(i + 1, len(prices)):
                if j in used:
                    continue
                p2 = prices[j]
                if p1 and abs(p1 - p2) / p1 < 0.0005:
                    cl.append(p2)
                    used.add(j)
            if len(cl) >= 2:
                out.append((statistics.mean(cl), len(cl)))
        return out

    def signal(self, price: float, direction: Direction) -> tuple[float, list[str]]:
        if not self.levels:
            return 0.0, []
        tol = price * 0.0003
        for lv in self.levels[:5]:
            if abs(price - lv["price"]) < tol:
                s = min(1.0, float(lv["strength"]) / 5)
                if lv["type"] == "SUPPORT" and direction == "UP":
                    return 0.15 * s, [f"BOUNCE_SUPPORT({lv['price']:.6f})"]
                if lv["type"] == "RESISTANCE" and direction == "DOWN":
                    return 0.15 * s, [f"REJECT_RESIST({lv['price']:.6f})"]
        return 0.0, []


class UltraSignalEngine:
    def __init__(self) -> None:
        self.micro = MicrostructureAnalyzer(
            tick_history_size=100,
            momentum_window=10,
            pressure_window=15,
            ofi_threshold=0.20,
        )
        self.regime = RegimeDetector(volatility_lookback=30, trend_detection_period=20)
        self.patt = PatternRecognizer()
        self.level = LevelAnalyzer()
        self.learning_ticks = 0

    def on_tick(self, mid: float) -> Signal | None:
        self.learning_ticks += 1
        self.micro.update_mid(mid)
        self.regime.update(mid)
        self.patt.update(mid)
        self.level.update(mid)
        if not self.micro.ready:
            return None
        return self._fuse(mid)

    def _fuse(self, price: float) -> Signal:
        up = 0.0
        dn = 0.0
        reasons: list[str] = []

        mu, md, mr = self.micro.contribution()
        up += mu * 0.40
        dn += md * 0.40
        reasons += mr

        patterns = self.patt.detect()
        for pat in patterns:
            w = 0.25 * float(pat["strength"])
            if pat["direction"] == "UP":
                up += w
            else:
                dn += w
            reasons.append(f"PAT_{pat['type']}({float(pat['strength']):.2f})")

        lu, lru = self.level.signal(price, "UP")
        ld, lrd = self.level.signal(price, "DOWN")
        up += lu * 0.20
        dn += ld * 0.20
        reasons += (lru if lu > ld else lrd)

        for d in ("UP", "DOWN"):
            ok, sc = self.regime.favorable(d)  # type: ignore[arg-type]
            if ok:
                if d == "UP":
                    up += sc * 0.15
                    reasons.append(f"REGIME_UP({self.regime.regime.value})")
                else:
                    dn += sc * 0.15
                    reasons.append(f"REGIME_DN({self.regime.regime.value})")

        tot = up + dn
        if tot <= 0:
            return Signal(direction=None, confidence=0.0, strength=SignalStrength.NEUTRAL, reasons=reasons, market_regime=self.regime.regime)

        if up > dn:
            direction: Direction | None = "UP"
            conf = up / (tot + 0.01)
        elif dn > up:
            direction = "DOWN"
            conf = dn / (tot + 0.01)
        else:
            return Signal(direction=None, confidence=0.5, strength=SignalStrength.NEUTRAL, reasons=reasons, market_regime=self.regime.regime)

        # mild volatility penalty
        if self.regime.regime == MarketRegime.VOLATILE:
            conf *= 0.70

        conf = _clamp(conf, 0.0, 0.99)

        if conf >= 0.85:
            strength = SignalStrength.STRONG_BUY if direction == "UP" else SignalStrength.STRONG_SELL
        elif conf >= 0.70:
            strength = SignalStrength.BUY if direction == "UP" else SignalStrength.SELL
        elif conf >= 0.55:
            strength = SignalStrength.NEUTRAL
        else:
            direction = None
            strength = SignalStrength.NEUTRAL

        confluence = sum(
            [
                mu > 0.1 or md > 0.1,
                len(patterns) > 0,
                lu > 0.05 or ld > 0.05,
                self.regime.regime != MarketRegime.UNKNOWN,
            ]
        ) / 4.0

        return Signal(
            direction=direction,
            confidence=float(conf),
            strength=strength,
            reasons=reasons,
            confluence_score=float(confluence),
            market_regime=self.regime.regime,
        )


def compute_strategy_signal(
    *,
    symbol: str,
    ticks: list[Tick],
    min_learning_ticks: int,
    min_confidence: float,
) -> tuple[Direction | None, float, list[str], str] | None:
    """
    Stateless helper for one-shot evaluation (used if you don't want state).
    Returns (direction, confidence, reasons, regime) or None if not ready.
    """
    if not ticks:
        return None
    engine = UltraSignalEngine()
    # simulate learning from history
    for t in ticks:
        engine.on_tick(t.price)
    sig = engine._fuse(ticks[-1].price) if engine.micro.ready else None
    if sig is None or sig.direction is None:
        return None
    if engine.learning_ticks < int(min_learning_ticks):
        return None
    if float(sig.confidence) < float(min_confidence):
        return None
    return sig.direction, float(sig.confidence), sig.reasons[:10], sig.market_regime.value

