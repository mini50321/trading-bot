from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.observability.log import log_event
from app.repo.trades import trades_repo
from app.services.trade_engine import trade_engine

logger = logging.getLogger(__name__)


class SettlementWorker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

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
            interval = max(0.2, float(get_settings().settlement_poll_interval_seconds))
            try:
                now = datetime.now(timezone.utc)
                for _ in range(100):
                    if self._stop.is_set():
                        break
                    trade = await trades_repo.claim_one_due_for_settlement(now)
                    if trade is None:
                        break
                    log_event(
                        "settlement.claimed",
                        trade_id=trade.trade_id,
                        telegram_id=trade.telegram_id,
                        broker=trade.broker,
                        symbol=trade.symbol,
                    )
                    await trade_engine.finalize_settlement(trade)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("settlement worker tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass


settlement_worker = SettlementWorker()
