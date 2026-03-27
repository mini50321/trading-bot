from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.config import get_settings
from app.domain.execution import WebhookSignalIn
from app.observability.log import log_event, log_exception
from app.repo.signals import signals_repo
from app.repo.system import system_repo
from app.repo.users import users_repo
from app.services.assets import assets
from app.services.market_data import market_data
from app.services.ultra_precision import UltraSignalEngine


@dataclass
class _CooldownKey:
    symbol: str
    direction: str


class StrategyWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_emit: dict[_CooldownKey, float] = {}
        self._engines: dict[str, UltraSignalEngine] = {}
        self._last_tick_ts: dict[str, float] = {}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        t = self._task
        self._task = None
        await t

    async def _run(self) -> None:
        while not self._stop.is_set():
            s = get_settings()
            interval = max(0.2, float(s.strategy_poll_interval_seconds))
            try:
                if not s.strategy_enabled_global:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass
                    continue
                if not await system_repo.get_global_trading_enabled():
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass
                    continue

                users = await users_repo.list_users(limit=5000)
                symbols: set[str] = set()
                for u in users:
                    if u.blocked:
                        continue
                    if not u.settings.trading_enabled:
                        continue
                    if not u.settings.strategy_enabled:
                        continue
                    for a in u.settings.assets:
                        if a:
                            symbols.add(a.strip().lower())

                if not symbols:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass
                    continue

                for sym in sorted(symbols):
                    if self._stop.is_set():
                        break
                    eff_payout = max(
                        float(s.global_min_payout_percent or 0.0),
                        float(s.trade_min_payout_floor_percent or 0.0),
                    )
                    min_p = eff_payout if eff_payout > 0 else None
                    tradable, _reason = assets.is_tradable(
                        sym,
                        min_payout_percent=min_p,
                        require_otc=s.trade_otc_only,
                    )
                    if not tradable:
                        continue
                    ticks = await market_data.get_recent_ticks(sym, limit=200)
                    if not ticks:
                        continue
                    eng = self._engines.get(sym)
                    if eng is None:
                        eng = UltraSignalEngine()
                        self._engines[sym] = eng
                    last_ts = self._last_tick_ts.get(sym)
                    # feed only new ticks (ts from WS may be epoch; it's fine)
                    new_ticks = ticks if last_ts is None else [t for t in ticks if float(t.ts) > float(last_ts)]
                    if new_ticks:
                        self._last_tick_ts[sym] = float(new_ticks[-1].ts)
                    for t in new_ticks:
                        sig = eng.on_tick(t.price)
                    sig = eng.on_tick(ticks[-1].price) if not new_ticks else sig  # ensure last computed
                    if sig is None or sig.direction is None:
                        continue
                    if eng.learning_ticks < int(s.strategy_min_learning_ticks):
                        continue
                    if float(sig.confidence) < float(s.strategy_min_confidence):
                        continue

                    # Debounce per symbol+direction
                    k = _CooldownKey(symbol=sym, direction=sig.direction)
                    now = time.monotonic()
                    last = self._last_emit.get(k)
                    cooldown = max(0.5, float(s.strategy_emit_cooldown_seconds))
                    if last is not None and (now - last) < cooldown:
                        continue
                    self._last_emit[k] = now

                    bucket = int(time.time() // max(1, int(s.strategy_bucket_seconds)))
                    signal_id = f"strategy:{sym}:{sig.direction}:{bucket}"
                    sig = WebhookSignalIn(
                        source="strategy",
                        signal_id=signal_id,
                        symbol=sym,
                        direction=sig.direction,
                        payload={
                            "confidence": float(sig.confidence),
                            "strength": getattr(sig.strength, "label", str(sig.strength)),
                            "reasons": sig.reasons[:10],
                            "market_regime": getattr(sig.market_regime, "value", str(sig.market_regime)),
                            "expiry_seconds": int(s.strategy_signal_expiry_seconds),
                        },
                    )
                    created, stored = await signals_repo.store(sig)
                    if not created:
                        continue
                    log_event(
                        "strategy.signal",
                        signal_id=stored.signal_id,
                        symbol=stored.symbol,
                        direction=stored.direction,
                        confidence=sig.payload.get("confidence"),
                    )
                    # TradeEngine fanouts to eligible users
                    # (settlement handled by worker)
                    from app.services.trade_engine import trade_engine

                    await trade_engine.on_signal(stored)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                # Expected from internal wait_for timeouts; not an error.
                pass
            except Exception as e:
                log_exception("strategy.tick_failed", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


strategy_worker = StrategyWorker()

