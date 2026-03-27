from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.domain.execution import StoredSignal, Trade
from app.integrations.pocketoption.errors import PocketOptionHttpError
from app.integrations.pocketoption.jsonpath import get_by_dotted_path
from app.repo.affiliate import affiliate_repo
from app.repo.credentials import credentials_repo
from app.repo.system import system_repo
from app.repo.trades import trades_repo
from app.repo.users import users_repo
from app.observability.log import log_event, log_exception, log_warning
from app.services.assets import assets
from app.services.market_data import market_data
from app.services.pocketoption_sessions import pocketoption_sessions


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start_utc(now: datetime) -> datetime:
    return datetime(now.year, now.month, now.day, tzinfo=timezone.utc)


class TradeEngine:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._win_profit_percent = 0.80
        self._loss_percent = 1.00

    @staticmethod
    def _csv_states(raw: str) -> set[str]:
        return {x.strip().lower() for x in raw.split(",") if x.strip()}

    async def _settle_from_broker(
        self,
        telegram_id: int,
        broker_trade_id: str,
        stake: float,
        win_pct: float,
        loss_pct: float,
    ) -> dict[str, Any]:
        settings = get_settings()
        extra = float(settings.po_trade_result_extra_wait_seconds)
        if extra > 0:
            await asyncio.sleep(extra)

        win_s = self._csv_states(settings.po_trade_result_win_states)
        loss_s = self._csv_states(settings.po_trade_result_loss_states)
        draw_s = self._csv_states(settings.po_trade_result_draw_states)
        open_s = self._csv_states(settings.po_trade_result_open_states)

        interval = max(0.05, float(settings.po_trade_result_poll_interval_seconds))
        max_polls = max(1, int(settings.po_trade_result_max_polls))

        pnl_path = settings.po_trade_result_pnl_path.strip()
        state_path = settings.po_trade_result_state_path.strip()
        exit_px_path = settings.po_trade_result_exit_price_path.strip()

        last: dict[str, Any] = {}
        for _ in range(max_polls):
            try:

                async def _fetch(c, s):
                    return await c.trade_result(s, broker_trade_id)

                last = await pocketoption_sessions.call(telegram_id, _fetch)
            except PocketOptionHttpError:
                await asyncio.sleep(interval)
                continue

            exit_px = None
            if exit_px_path:
                v = get_by_dotted_path(last, exit_px_path)
                if v is not None:
                    try:
                        exit_px = float(v)
                    except Exception:
                        exit_px = None

            if pnl_path:
                raw_pnl = get_by_dotted_path(last, pnl_path)
                if raw_pnl is not None and raw_pnl != "":
                    try:
                        return {
                            "status": "settled",
                            "pnl": float(raw_pnl),
                            "exit_price": exit_px,
                            "result_body": last,
                            "error": None,
                        }
                    except Exception:
                        pass

            if state_path:
                raw_st = get_by_dotted_path(last, state_path)
                if raw_st is not None:
                    sv = str(raw_st).strip().lower()
                    if sv in open_s:
                        await asyncio.sleep(interval)
                        continue
                    if sv in win_s:
                        return {
                            "status": "settled",
                            "pnl": stake * win_pct,
                            "exit_price": exit_px,
                            "result_body": last,
                            "error": None,
                        }
                    if sv in loss_s:
                        return {
                            "status": "settled",
                            "pnl": -(stake * loss_pct),
                            "exit_price": exit_px,
                            "result_body": last,
                            "error": None,
                        }
                    if sv in draw_s:
                        return {
                            "status": "settled",
                            "pnl": 0.0,
                            "exit_price": exit_px,
                            "result_body": last,
                            "error": None,
                        }
                    return {
                        "status": "failed",
                        "pnl": None,
                        "exit_price": exit_px,
                        "result_body": last,
                        "error": f"unknown_state:{sv}",
                    }

            await asyncio.sleep(interval)

        return {
            "status": "failed",
            "pnl": None,
            "exit_price": None,
            "result_body": last,
            "error": "result_timeout",
        }

    async def on_signal(self, signal: StoredSignal) -> dict:
        if not await system_repo.get_global_trading_enabled():
            log_event(
                "signal.skipped",
                reason="global_trading_disabled",
                signal_id=signal.signal_id,
                symbol=signal.symbol.strip().lower(),
            )
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

        async def _safe(tid: int) -> dict[str, Any]:
            try:
                return await self._create_and_open(tid, symbol, signal)
            except Exception as e:
                log_exception(
                    "trade.engine_error",
                    e,
                    telegram_id=tid,
                    symbol=symbol,
                    signal_id=signal.signal_id,
                )
                return {
                    "telegram_id": tid,
                    "status": "engine_error",
                    "error": type(e).__name__,
                    "detail": str(e)[:500],
                }

        if not eligible:
            log_event(
                "signal.dispatch",
                signal_id=signal.signal_id,
                symbol=symbol,
                direction=signal.direction,
                eligible=0,
                breakdown="",
            )
            return {"eligible": 0, "results": []}

        results = await asyncio.gather(*[_safe(u.telegram_id) for u in eligible])
        cnt = Counter()
        for r in results:
            if isinstance(r, dict):
                st = r.get("status")
                if st:
                    cnt[str(st)] += 1
        log_event(
            "signal.dispatch",
            signal_id=signal.signal_id,
            symbol=symbol,
            direction=signal.direction,
            eligible=len(eligible),
            breakdown=",".join(f"{k}:{cnt[k]}" for k in sorted(cnt)),
        )
        return {"eligible": len(eligible), "results": list(results)}

    async def finalize_settlement(self, t: Trade) -> None:
        trade_id = t.trade_id
        telegram_id = t.telegram_id
        symbol = t.symbol.strip().lower()
        stake = float(t.stake)
        place_raw: dict[str, Any] = dict(t.result) if t.result else {}

        try:
            exit_ts = asyncio.get_running_loop().time()
            cfg = get_settings()
            broker_settle = (
                t.broker == "pocketoption"
                and t.broker_trade_id
                and cfg.pocketoption_trade_result_enabled()
            )

            if broker_settle:
                out = await self._settle_from_broker(
                    telegram_id,
                    str(t.broker_trade_id),
                    stake,
                    float(t.win_profit_percent or self._win_profit_percent),
                    float(t.loss_percent or self._loss_percent),
                )
                body = out.get("result_body") if isinstance(out.get("result_body"), dict) else {}
                merged = {**place_raw, **body}
                await trades_repo.update(
                    trade_id,
                    {
                        "exit_price": out.get("exit_price"),
                        "exit_ts": exit_ts,
                        "status": out["status"],
                        "pnl": out.get("pnl"),
                        "result": merged,
                        "error": out.get("error"),
                    },
                )
                log_event(
                    "settlement.done",
                    trade_id=trade_id,
                    telegram_id=telegram_id,
                    broker="pocketoption",
                    status=out["status"],
                    pnl=out.get("pnl"),
                    err=out.get("error"),
                )
                return

            entry_price = t.entry_price
            prices2 = await market_data.get_prices([symbol])
            exit_price = prices2.get(symbol)
            status = "settled" if entry_price is not None and exit_price is not None else "failed"
            pnl = None
            wpp = float(t.win_profit_percent or self._win_profit_percent)
            lp = float(t.loss_percent or self._loss_percent)
            if status == "settled":
                if t.direction == "UP":
                    pnl = (stake * wpp) if exit_price > entry_price else -(stake * lp)
                else:
                    pnl = (stake * wpp) if exit_price < entry_price else -(stake * lp)

            await trades_repo.update(
                trade_id,
                {
                    "exit_price": exit_price,
                    "exit_ts": exit_ts,
                    "status": status,
                    "pnl": pnl,
                },
            )
            log_event(
                "settlement.done",
                trade_id=trade_id,
                telegram_id=telegram_id,
                broker=t.broker,
                status=status,
                pnl=pnl,
            )
        except Exception as e:
            await trades_repo.update(
                trade_id,
                {
                    "status": "failed",
                    "error": f"{type(e).__name__}: {str(e)[:400]}",
                },
            )
            log_warning(
                "settlement.crashed",
                trade_id=trade_id,
                telegram_id=telegram_id,
                exc=type(e).__name__,
            )

    async def _create_and_open(self, telegram_id: int, symbol: str, signal: StoredSignal) -> dict:
        trade_id = uuid.uuid4().hex
        stake = float(max(0.0, signal.payload.get("stake") or 0.0)) if isinstance(signal.payload, dict) else 0.0
        user = await users_repo.get_user(telegram_id)
        if user is None:
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "failed"}
        if user.blocked or not user.settings.trading_enabled:
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "skipped"}

        ok_aff, aff_reason = await affiliate_repo.is_trading_allowed(telegram_id)
        if not ok_aff:
            log_event(
                "trade.affiliate_blocked",
                telegram_id=telegram_id,
                trade_id=trade_id,
                symbol=symbol,
                reason=aff_reason,
            )
            return {
                "telegram_id": telegram_id,
                "trade_id": trade_id,
                "status": "affiliate_blocked",
                "reason": aff_reason,
            }

        cfg = get_settings()
        eff_min_payout = max(
            float(user.settings.min_payout_percent or 0.0),
            float(cfg.global_min_payout_percent or 0.0),
            float(cfg.trade_min_payout_floor_percent or 0.0),
        )
        min_p_req = eff_min_payout if eff_min_payout > 0 else None
        ok, reason = assets.is_tradable(
            symbol,
            min_payout_percent=min_p_req,
            require_otc=cfg.trade_otc_only,
        )
        if not ok:
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "asset_blocked", "reason": reason}

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
        if user.settings.max_stake_per_trade > 0:
            stake = min(float(stake), float(user.settings.max_stake_per_trade))
        if stake <= 0:
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "risk_blocked", "reason": "invalid_stake"}

        if user.settings.max_stake_per_day > 0:
            stake_used = await trades_repo.sum_stake_since(telegram_id, since)
            if stake_used + float(stake) > float(user.settings.max_stake_per_day):
                return {
                    "telegram_id": telegram_id,
                    "trade_id": trade_id,
                    "status": "risk_blocked",
                    "reason": "max_stake_per_day",
                }

        expiry_seconds = int(signal.payload.get("expiry_seconds") or user.settings.expiry_seconds) if isinstance(signal.payload, dict) else int(user.settings.expiry_seconds)
        expiry_seconds = max(1, min(3600, expiry_seconds))

        resolved_asset, _ = assets.resolve(symbol)
        if resolved_asset is None:
            return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "asset_blocked", "reason": "asset_not_mapped"}

        settings = get_settings()
        use_po = settings.pocketoption_place_trade_enabled()
        place_raw: dict[str, Any] = {}

        if use_po:
            if await credentials_repo.get_credentials(telegram_id) is None:
                return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "no_credentials"}

            tlock = await pocketoption_sessions.trade_lock(telegram_id)
            async with tlock:
                try:
                    async def _place(c, s):
                        return await c.place_trade(
                            s,
                            asset_id=resolved_asset.asset_id,
                            amount=float(stake),
                            direction=signal.direction,
                            expiry_seconds=expiry_seconds,
                        )

                    raw, broker_id = await pocketoption_sessions.call(telegram_id, _place)
                    place_raw = raw if isinstance(raw, dict) else {}
                except PocketOptionHttpError as e:
                    err_body = ""
                    try:
                        err_body = (e.body or b"").decode("utf-8", errors="replace")[:4000]
                    except Exception:
                        pass
                    fail = Trade(
                        trade_id=trade_id,
                        telegram_id=telegram_id,
                        broker="pocketoption",
                        broker_trade_id=None,
                        symbol=symbol,
                        direction=signal.direction,
                        stake=stake,
                        expiry_seconds=expiry_seconds,
                        placed_at=now,
                        expiry_at=now + timedelta(seconds=expiry_seconds),
                        entry_price=None,
                        entry_ts=None,
                        exit_price=None,
                        exit_ts=None,
                        status="failed",
                        pnl=None,
                        win_profit_percent=self._win_profit_percent,
                        loss_percent=self._loss_percent,
                        signal_source=signal.source,
                        signal_id=signal.signal_id,
                        created_at=now,
                        result={"http_status": e.status, "op": e.op, "body": err_body},
                        error=f"{e.op} {e.status}",
                    )
                    await trades_repo.create(fail)
                    log_warning(
                        "trade.place_failed",
                        trade_id=trade_id,
                        telegram_id=telegram_id,
                        symbol=symbol,
                        http_status=e.status,
                        op=e.op,
                    )
                    return {"telegram_id": telegram_id, "trade_id": trade_id, "status": "place_failed"}

            prices = await market_data.get_prices([symbol])
            entry_price = prices.get(symbol)
            entry_ts = asyncio.get_running_loop().time() if entry_price is not None else None
            t = Trade(
                trade_id=trade_id,
                telegram_id=telegram_id,
                broker="pocketoption",
                broker_trade_id=broker_id,
                symbol=symbol,
                direction=signal.direction,
                stake=stake,
                expiry_seconds=expiry_seconds,
                placed_at=now,
                expiry_at=now + timedelta(seconds=expiry_seconds),
                entry_price=entry_price,
                entry_ts=entry_ts,
                status="opened",
                pnl=None,
                win_profit_percent=self._win_profit_percent,
                loss_percent=self._loss_percent,
                signal_source=signal.source,
                signal_id=signal.signal_id,
                created_at=now,
                result=place_raw,
                error=None,
            )
        else:
            prices = await market_data.get_prices([symbol])
            entry_price = prices.get(symbol)
            entry_ts = None
            if entry_price is not None:
                entry_ts = asyncio.get_running_loop().time()

            t = Trade(
                trade_id=trade_id,
                telegram_id=telegram_id,
                broker="simulated",
                broker_trade_id=None,
                symbol=symbol,
                direction=signal.direction,
                stake=stake,
                expiry_seconds=expiry_seconds,
                placed_at=now,
                expiry_at=now + timedelta(seconds=expiry_seconds),
                entry_price=entry_price,
                entry_ts=entry_ts,
                status="opened" if entry_price is not None else "created",
                pnl=None,
                win_profit_percent=self._win_profit_percent,
                loss_percent=self._loss_percent,
                signal_source=signal.source,
                signal_id=signal.signal_id,
                created_at=now,
                result={},
                error=None,
            )
        await trades_repo.create(t)
        log_event(
            "trade.opened",
            trade_id=trade_id,
            telegram_id=telegram_id,
            broker=t.broker,
            symbol=symbol,
            direction=signal.direction,
            stake=stake,
            status=t.status,
            broker_trade_id=t.broker_trade_id,
            signal_id=signal.signal_id,
        )
        return {"telegram_id": telegram_id, "trade_id": trade_id, "status": t.status, "settlement": "queued"}


trade_engine = TradeEngine()

