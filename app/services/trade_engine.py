from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from app.domain.execution import StoredSignal, Trade
from app.repo.system import system_repo
from app.repo.trades import trades_repo
from app.repo.users import users_repo
from app.services.market_data import market_data


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


class TradeEngine:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._win_profit_percent = 0.80
        self._loss_percent = 1.00

    async def on_signal(self, signal: StoredSignal) -> dict:
        if not await system_repo.get_global_trading_enabled():
            return {"eligible": 0, "results": [], "global_trading": "disabled"}
        symbol = signal.symbol.strip().lower()
        users = await users_repo.list_users(limit=5000)
        eligible = []
        for u in users:
            if u.blocked:
                continue
            if not u.settings.trading_enabled:
                continue
            if symbol not in [a.lower() for a in u.settings.assets]:
                continue
            eligible.append(u)

        results = []
        for u in eligible:
            results.append(await self._create_and_settle(u.telegram_id, symbol, signal))
        return {"eligible": len(eligible), "results": results}

    async def _create_and_settle(self, telegram_id: int, symbol: str, signal: StoredSignal) -> dict:
        trade_id = uuid.uuid4().hex
        stake = float(max(0.0, signal.payload.get("stake") or 0.0)) if isinstance(signal.payload, dict) else 0.0
        user = await users_repo.get_user(telegram_id)
        if user is None:
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "failed"}
        if user.blocked or not user.settings.trading_enabled:
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "skipped"}

        now = _now()
        since = _day_start_utc(now)
        day_count, day_pnl = await trades_repo.stats_since(telegram_id, since)
        if user.settings.max_trades_per_day > 0 and day_count >= int(user.settings.max_trades_per_day):
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "risk_blocked"}
        if user.settings.max_loss_per_day > 0 and day_pnl <= -float(user.settings.max_loss_per_day):
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "risk_blocked"}
        if user.settings.max_consecutive_losses > 0:
            recent = await trades_repo.last_settled_results(telegram_id, int(user.settings.max_consecutive_losses))
            if len(recent) >= int(user.settings.max_consecutive_losses) and all(x < 0 for x in recent):
                return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "risk_blocked"}

        if user.settings.cooldown_seconds > 0:
            recent_trades = await trades_repo.list_recent_for_user(telegram_id, limit=1)
            if recent_trades:
                last = recent_trades[0]
                if last.exit_ts is not None:
                    try:
                        if (asyncio.get_running_loop().time() - float(last.exit_ts)) < float(
                            user.settings.cooldown_seconds
                        ):
                            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "cooldown"}
                    except Exception:
                        pass

        if stake <= 0:
            stake = float(user.settings.stake)
        expiry_seconds = int(signal.payload.get("expiry_seconds") or user.settings.expiry_seconds) if isinstance(signal.payload, dict) else int(user.settings.expiry_seconds)
        expiry_seconds = max(1, min(3600, expiry_seconds))

        prices = await market_data.get_prices([symbol])
        entry_price = prices.get(symbol)
        entry_ts = None
        if entry_price is not None:
            entry_ts = asyncio.get_running_loop().time()

        t = Trade(
            trade_id=trade_id,
            telegram_id=telegram_id,
            symbol=symbol,
            direction=signal.direction,
            stake=stake,
            expiry_seconds=expiry_seconds,
            entry_price=entry_price,
            entry_ts=entry_ts,
            status="opened" if entry_price is not None else "created",
            pnl=None,
            win_profit_percent=self._win_profit_percent,
            loss_percent=self._loss_percent,
            signal_source=signal.source,
            signal_id=signal.signal_id,
            created_at=now,
            error=None,
        )
        await trades_repo.create(t)

        await asyncio.sleep(expiry_seconds)

        prices2 = await market_data.get_prices([symbol])
        exit_price = prices2.get(symbol)
        exit_ts = asyncio.get_running_loop().time()
        status = "settled" if entry_price is not None and exit_price is not None else "failed"
        pnl = None
        if status == "settled":
            if signal.direction == "UP":
                pnl = (stake * self._win_profit_percent) if exit_price > entry_price else -(stake * self._loss_percent)
            else:
                pnl = (stake * self._win_profit_percent) if exit_price < entry_price else -(stake * self._loss_percent)

        await trades_repo.update(
            trade_id,
            {
                "exit_price": exit_price,
                "exit_ts": exit_ts,
                "status": status,
                "pnl": pnl,
            },
        )
        return {"telegram_id": telegram_id, "trade_id": trade_id, "status": status}


trade_engine = TradeEngine()

