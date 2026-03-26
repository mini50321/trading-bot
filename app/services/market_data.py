from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import websockets

from app.config import get_settings


@dataclass(frozen=True)
class Tick:
    ts: float
    price: float


class MarketDataService:
    def __init__(self) -> None:
        self._settings = None
        self._lock = asyncio.Lock()
        self._symbol_watchers: dict[str, set[int]] = defaultdict(set)
        self._user_symbols: dict[int, set[str]] = defaultdict(set)
        self._ticks: dict[str, deque[Tick]] = defaultdict(lambda: deque(maxlen=500))
        self._last_price: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._settings = get_settings()
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        t = self._task
        self._task = None
        await t
        self._settings = None

    async def watch(self, telegram_id: int, symbols: list[str]) -> None:
        norm = {s.strip().lower() for s in symbols if s.strip()}
        async with self._lock:
            for s in norm:
                self._symbol_watchers[s].add(telegram_id)
                self._user_symbols[telegram_id].add(s)

    async def unwatch(self, telegram_id: int, symbols: list[str] | None = None) -> None:
        async with self._lock:
            if symbols is None:
                to_remove = set(self._user_symbols.get(telegram_id, set()))
            else:
                to_remove = {s.strip().lower() for s in symbols if s.strip()}
            for s in to_remove:
                self._user_symbols[telegram_id].discard(s)
                ws = self._symbol_watchers.get(s)
                if ws is not None:
                    ws.discard(telegram_id)
                    if not ws:
                        self._symbol_watchers.pop(s, None)

    async def get_prices(self, symbols: list[str]) -> dict[str, float]:
        norm = [s.strip().lower() for s in symbols if s.strip()]
        async with self._lock:
            return {s: self._last_price[s] for s in norm if s in self._last_price}

    async def get_user_symbols(self, telegram_id: int) -> list[str]:
        async with self._lock:
            return sorted(self._user_symbols.get(telegram_id, set()))

    async def get_recent_ticks(self, symbol: str, limit: int = 50) -> list[Tick]:
        sym = (symbol or "").strip().lower()
        if not sym:
            return []
        limit = max(0, min(500, int(limit)))
        if limit == 0:
            return []
        async with self._lock:
            dq = self._ticks.get(sym)
            if not dq:
                return []
            if len(dq) <= limit:
                return list(dq)
            return list(dq)[-limit:]

    async def _current_symbols(self) -> list[str]:
        async with self._lock:
            return sorted(self._symbol_watchers.keys())

    async def _run(self) -> None:
        settings = self._settings or get_settings()
        url = settings.po_ws_url.strip()
        if not url:
            while not self._stop.is_set():
                await asyncio.sleep(1)
            return

        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    backoff = 1.0
                    await self._sync_subscriptions(ws)
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    sync_task = asyncio.create_task(self._sync_loop(ws))
                    done, pending = await asyncio.wait(
                        {recv_task, sync_task},
                        return_when=asyncio.FIRST_EXCEPTION,
                    )
                    for p in pending:
                        p.cancel()
                    for d in done:
                        exc = d.exception()
                        if exc is not None:
                            raise exc
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(30.0, backoff * 1.7)

    async def _sync_loop(self, ws) -> None:
        while not self._stop.is_set():
            await self._sync_subscriptions(ws)
            await asyncio.sleep(2.0)

    async def _sync_subscriptions(self, ws) -> None:
        settings = self._settings or get_settings()
        symbols = await self._current_symbols()
        payload = {
            "action": settings.po_ws_subscribe_action,
            "symbols": symbols,
        }
        await ws.send(json.dumps(payload))

    async def _recv_loop(self, ws) -> None:
        while not self._stop.is_set():
            raw = await ws.recv()
            try:
                data = json.loads(raw)
            except Exception:
                continue
            tick = self._parse_tick(data)
            if tick is None:
                continue
            symbol, ts, price = tick
            async with self._lock:
                self._last_price[symbol] = price
                self._ticks[symbol].append(Tick(ts=ts, price=price))

    def _parse_tick(self, data: dict[str, Any]) -> tuple[str, float, float] | None:
        settings = self._settings or get_settings()
        s_key = settings.po_ws_symbol_key
        p_key = settings.po_ws_price_key
        t_key = settings.po_ws_timestamp_key
        symbol = data.get(s_key)
        price = data.get(p_key)
        ts = data.get(t_key)
        if symbol is None or price is None:
            return None
        try:
            sym = str(symbol).strip().lower()
            pr = float(price)
        except Exception:
            return None
        if ts is None:
            tsf = time.time()
        else:
            try:
                tsf = float(ts)
            except Exception:
                tsf = time.time()
        return sym, tsf, pr


market_data = MarketDataService()

