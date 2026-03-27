from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.domain.types import User, UserSettings
from app.services.trade_engine import TradeEngine


def test_martingale_on_settled_win_resets_step() -> None:
    async def run() -> None:
        te = TradeEngine()
        u = User(
            telegram_id=99,
            created_at=datetime.now(timezone.utc),
            martingale_step=4,
            settings=UserSettings(martingale_enabled=True),
        )
        with patch("app.services.trade_engine.users_repo") as ur:
            ur.get_user = AsyncMock(return_value=u)
            ur.set_martingale_step = AsyncMock()
            await te._martingale_on_settled(99, 1.5)
            ur.set_martingale_step.assert_awaited_once_with(99, 0)

    asyncio.run(run())


def test_martingale_on_settled_loss_advances() -> None:
    async def run() -> None:
        te = TradeEngine()
        u = User(
            telegram_id=101,
            created_at=datetime.now(timezone.utc),
            martingale_step=1,
            settings=UserSettings(martingale_enabled=True, martingale_max_levels=7),
        )
        with patch("app.services.trade_engine.users_repo") as ur:
            ur.get_user = AsyncMock(return_value=u)
            ur.set_martingale_step = AsyncMock()
            await te._martingale_on_settled(101, -2.0)
            ur.set_martingale_step.assert_awaited_once_with(101, 2)

    asyncio.run(run())


def test_martingale_on_settled_capped_at_max_step() -> None:
    async def run() -> None:
        te = TradeEngine()
        u = User(
            telegram_id=102,
            created_at=datetime.now(timezone.utc),
            martingale_step=6,
            settings=UserSettings(martingale_enabled=True, martingale_max_levels=7),
        )
        with patch("app.services.trade_engine.users_repo") as ur:
            ur.get_user = AsyncMock(return_value=u)
            ur.set_martingale_step = AsyncMock()
            await te._martingale_on_settled(102, -1.0)
            ur.set_martingale_step.assert_awaited_once_with(102, 6)

    asyncio.run(run())


def test_martingale_on_settled_skips_when_disabled() -> None:
    async def run() -> None:
        te = TradeEngine()
        u = User(
            telegram_id=103,
            created_at=datetime.now(timezone.utc),
            martingale_step=2,
            settings=UserSettings(martingale_enabled=False),
        )
        with patch("app.services.trade_engine.users_repo") as ur:
            ur.get_user = AsyncMock(return_value=u)
            ur.set_martingale_step = AsyncMock()
            await te._martingale_on_settled(103, -1.0)
            ur.set_martingale_step.assert_not_called()

    asyncio.run(run())


def test_martingale_on_settled_skips_when_pnl_none() -> None:
    async def run() -> None:
        te = TradeEngine()
        with patch("app.services.trade_engine.users_repo") as ur:
            ur.set_martingale_step = AsyncMock()
            await te._martingale_on_settled(104, None)
            ur.set_martingale_step.assert_not_called()

    asyncio.run(run())
