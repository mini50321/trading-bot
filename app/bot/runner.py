from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers import router
from app.config import get_settings
from app.db.mongo import mongo
from app.services.market_data import market_data
from app.services.pocketoption_auth import pocketoption_auth


async def run_bot() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await mongo.connect()
    await pocketoption_auth.start()
    await market_data.start()
    settings = get_settings()
    bot = Bot(token=settings.require_bot_token(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await market_data.stop()
        await pocketoption_auth.close()
        await mongo.close()


async def run_bot_forever() -> None:
    while True:
        try:
            await run_bot()
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(3)

