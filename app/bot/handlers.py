from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.formatting import user_status_text
from app.bot.keyboards import main_menu, settings_menu
from app.bot.state import ConnectFlow, SettingsFlow
from app.config import get_settings
from app.repo.affiliate import affiliate_repo
from app.repo.credentials import credentials_repo
from app.repo.system import system_repo
from app.repo.users import users_repo
from app.services.assets import assets
from app.services.market_data import market_data
from app.services.pocketoption_auth import pocketoption_auth

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids()


async def _ensure_user_from_message(message: Message):
    u = message.from_user
    if u is None:
        return None
    return await users_repo.ensure_user(u.id, u.username, u.first_name)


async def _ensure_user_from_callback(cb: CallbackQuery):
    u = cb.from_user
    return await users_repo.ensure_user(u.id, u.username, u.first_name)


@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    await message.answer("welcome", reply_markup=main_menu(user.settings.trading_enabled))


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(
        "/start\n"
        "/status\n"
        "/settings\n"
        "/connect\n"
        "/disconnect\n"
        "/account\n"
        "/watch <symbols>\n"
        "/unwatch <symbols|all>\n"
        "/prices\n"
        "/enable\n"
        "/disable\n"
        "/global_on (admin)\n"
        "/global_off (admin)\n"
        "/admin_users (admin)\n"
        "/admin_block <telegram_id> (admin)\n"
        "/admin_unblock <telegram_id> (admin)"
    )


@router.message(Command("status"))
async def status_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    aff = await affiliate_repo.describe_status(user.telegram_id)
    await message.answer(
        user_status_text(user) + f"\naffiliate: {aff}",
        reply_markup=main_menu(user.settings.trading_enabled),
    )


@router.message(Command("settings"))
async def settings_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    await message.answer("settings", reply_markup=settings_menu())


@router.message(Command("enable"))
async def enable_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    await users_repo.set_trading_enabled(user.telegram_id, True)
    user = await users_repo.get_user(user.telegram_id)
    if user is None:
        return
    await message.answer("trading enabled", reply_markup=main_menu(user.settings.trading_enabled))


@router.message(Command("disable"))
async def disable_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    await users_repo.set_trading_enabled(user.telegram_id, False)
    user = await users_repo.get_user(user.telegram_id)
    if user is None:
        return
    await message.answer("trading disabled", reply_markup=main_menu(user.settings.trading_enabled))


@router.message(Command("connect"))
async def connect_cmd(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    await state.set_state(ConnectFlow.email)
    await message.answer("send pocketoption email")


@router.message(ConnectFlow.email)
async def connect_email(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    email = (message.text or "").strip()
    if "@" not in email or len(email) < 5:
        await message.answer("invalid email")
        return
    await state.update_data(email=email)
    await state.set_state(ConnectFlow.password)
    await message.answer("send pocketoption password")


@router.message(ConnectFlow.password)
async def connect_password(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    data = await state.get_data()
    email = str(data.get("email") or "").strip()
    password = (message.text or "").strip()
    if not email or not password:
        await message.answer("missing email or password")
        await state.clear()
        return
    await credentials_repo.set_credentials(user.telegram_id, email, password)
    await affiliate_repo.link_telegram_id(email, user.telegram_id)
    await state.clear()
    try:
        await pocketoption_auth.login_for_user(user.telegram_id)
        await message.answer("connected")
    except Exception:
        await message.answer("saved credentials but login failed. check endpoints/config.")


@router.message(Command("disconnect"))
async def disconnect_cmd(message: Message, state: FSMContext):
    await state.clear()
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    await credentials_repo.delete_credentials(user.telegram_id)
    await affiliate_repo.clear_telegram_link(user.telegram_id)
    await message.answer("disconnected")


@router.message(Command("account"))
async def account_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    try:
        profile = await pocketoption_auth.profile(user.telegram_id)
        balance = await pocketoption_auth.balance(user.telegram_id)
        await message.answer(f"profile: {profile}\n\nbalance: {balance}")
    except Exception as e:
        await message.answer(f"account lookup failed: {type(e).__name__}")


@router.message(Command("watch"))
async def watch_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("usage: /watch eurusd,btcusd")
        return
    symbols = [s.strip() for s in parts[1].split(",") if s.strip()]
    if not symbols:
        await message.answer("no symbols")
        return
    lowered = [s.lower() for s in symbols]
    await users_repo.update_settings(user.telegram_id, {"assets": lowered})
    await market_data.watch(user.telegram_id, symbols)
    st = get_settings()
    eff = max(
        float(user.settings.min_payout_percent or 0.0),
        float(st.global_min_payout_percent or 0.0),
        float(st.trade_min_payout_floor_percent or 0.0),
    )
    min_p = eff if eff > 0 else None
    warns: list[str] = []
    for sym in lowered:
        ok, reason = assets.is_tradable(sym, min_payout_percent=min_p, require_otc=st.trade_otc_only)
        if not ok:
            warns.append(f"{sym}: {reason}")
    msg = "watching updated"
    if warns:
        msg += "\n\nnot tradable with current OTC/payout rules:\n" + "\n".join(warns)
    await message.answer(msg)


@router.message(Command("unwatch"))
async def unwatch_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("usage: /unwatch eurusd,btcusd or /unwatch all")
        return
    arg = parts[1].strip().lower()
    if arg == "all":
        await market_data.unwatch(user.telegram_id, None)
        await users_repo.update_settings(user.telegram_id, {"assets": []})
        await message.answer("watching cleared")
        return
    symbols = [s.strip() for s in arg.split(",") if s.strip()]
    if not symbols:
        await message.answer("no symbols")
        return
    current = set(user.settings.assets)
    for s in symbols:
        current.discard(s.lower())
    await users_repo.update_settings(user.telegram_id, {"assets": sorted(current)})
    await market_data.unwatch(user.telegram_id, symbols)
    await message.answer("watching updated")


@router.message(Command("prices"))
async def prices_cmd(message: Message):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        return
    symbols = await market_data.get_user_symbols(user.telegram_id)
    if not symbols:
        symbols = user.settings.assets
    if not symbols:
        await message.answer("no watched symbols. use /watch")
        return
    prices = await market_data.get_prices(symbols)
    if not prices:
        await message.answer("no prices yet")
        return
    lines = [f"{k}: {v}" for k, v in sorted(prices.items())]
    await message.answer("\n".join(lines))


@router.callback_query(F.data == "menu:status")
async def menu_status(cb: CallbackQuery):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    aff = await affiliate_repo.describe_status(user.telegram_id)
    await cb.message.answer(
        user_status_text(user) + f"\naffiliate: {aff}",
        reply_markup=main_menu(user.settings.trading_enabled),
    )
    await cb.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(cb: CallbackQuery):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await cb.message.answer("settings", reply_markup=settings_menu())
    await cb.answer()


@router.callback_query(F.data == "menu:back")
async def menu_back(cb: CallbackQuery):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await cb.message.answer("menu", reply_markup=main_menu(user.settings.trading_enabled))
    await cb.answer()


@router.callback_query(F.data == "trade:enable")
async def trade_enable(cb: CallbackQuery):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await users_repo.set_trading_enabled(user.telegram_id, True)
    user = await users_repo.get_user(user.telegram_id)
    if user is None:
        await cb.answer()
        return
    await cb.message.answer("trading enabled", reply_markup=main_menu(user.settings.trading_enabled))
    await cb.answer()


@router.callback_query(F.data == "trade:disable")
async def trade_disable(cb: CallbackQuery):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await users_repo.set_trading_enabled(user.telegram_id, False)
    user = await users_repo.get_user(user.telegram_id)
    if user is None:
        await cb.answer()
        return
    await cb.message.answer("trading disabled", reply_markup=main_menu(user.settings.trading_enabled))
    await cb.answer()


@router.callback_query(F.data == "set:stake")
async def set_stake_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.stake)
    await cb.message.answer("send stake amount (number)")
    await cb.answer()


@router.message(SettingsFlow.stake)
async def set_stake_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    try:
        stake = float(message.text.strip())
    except Exception:
        await message.answer("invalid number")
        return
    if stake <= 0:
        await message.answer("stake must be > 0")
        return
    await users_repo.update_settings(user.telegram_id, {"stake": stake})
    await state.clear()
    user = await users_repo.get_user(user.telegram_id)
    if user is None:
        return
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:expiry")
async def set_expiry_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.expiry)
    await cb.message.answer("send expiry in seconds (integer)")
    await cb.answer()


@router.message(SettingsFlow.expiry)
async def set_expiry_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        expiry = int(txt)
    except Exception:
        await message.answer("invalid integer")
        return
    if expiry < 1 or expiry > 3600:
        await message.answer("expiry must be between 1 and 3600")
        return
    await users_repo.update_settings(user.telegram_id, {"expiry_seconds": expiry})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:assets")
async def set_assets_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.assets)
    await cb.message.answer("send assets as comma-separated symbols (example: eurusd, btcusd)")
    await cb.answer()


@router.message(SettingsFlow.assets)
async def set_assets_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    assets = [a.strip().lower() for a in txt.split(",") if a.strip()]
    if len(assets) > 25:
        await message.answer("too many assets (max 25)")
        return
    await users_repo.update_settings(user.telegram_id, {"assets": assets})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:min_payout_percent")
async def set_min_payout_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.min_payout_percent)
    await cb.message.answer("send min payout percent (0 disables). requires payout in PO_ASSET_MAP_JSON")
    await cb.answer()


@router.message(SettingsFlow.min_payout_percent)
async def set_min_payout_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        v = float(txt)
    except Exception:
        await message.answer("invalid number")
        return
    if v < 0 or v > 100:
        await message.answer("out of range (0-100)")
        return
    await users_repo.update_settings(user.telegram_id, {"min_payout_percent": v})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:max_stake_per_trade")
async def set_max_stake_trade_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.max_stake_per_trade)
    await cb.message.answer("send max stake per trade (0 disables cap)")
    await cb.answer()


@router.message(SettingsFlow.max_stake_per_trade)
async def set_max_stake_trade_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        v = float(txt)
    except Exception:
        await message.answer("invalid number")
        return
    if v < 0 or v > 1e12:
        await message.answer("out of range")
        return
    await users_repo.update_settings(user.telegram_id, {"max_stake_per_trade": v})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:max_stake_per_day")
async def set_max_stake_day_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.max_stake_per_day)
    await cb.message.answer("send max total stake per day (0 disables). counts sum of trade stakes since utc midnight")
    await cb.answer()


@router.message(SettingsFlow.max_stake_per_day)
async def set_max_stake_day_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        v = float(txt)
    except Exception:
        await message.answer("invalid number")
        return
    if v < 0 or v > 1e12:
        await message.answer("out of range")
        return
    await users_repo.update_settings(user.telegram_id, {"max_stake_per_day": v})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:strategy_enabled")
async def toggle_strategy(cb: CallbackQuery):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    new_val = not bool(user.settings.strategy_enabled)
    await users_repo.update_settings(user.telegram_id, {"strategy_enabled": new_val})
    user2 = await users_repo.get_user(user.telegram_id)
    if user2 is not None:
        await cb.message.answer(f"strategy {'enabled' if user2.settings.strategy_enabled else 'disabled'}", reply_markup=settings_menu())
    await cb.answer()


@router.callback_query(F.data == "set:max_trades_per_day")
async def set_mtpd_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.max_trades_per_day)
    await cb.message.answer("send max trades per day (0 disables limit)")
    await cb.answer()


@router.message(SettingsFlow.max_trades_per_day)
async def set_mtpd_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        v = int(txt)
    except Exception:
        await message.answer("invalid integer")
        return
    if v < 0 or v > 100000:
        await message.answer("out of range")
        return
    await users_repo.update_settings(user.telegram_id, {"max_trades_per_day": v})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:max_loss_per_day")
async def set_mlpd_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.max_loss_per_day)
    await cb.message.answer("send max loss per day (0 disables limit)")
    await cb.answer()


@router.message(SettingsFlow.max_loss_per_day)
async def set_mlpd_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        v = float(txt)
    except Exception:
        await message.answer("invalid number")
        return
    if v < 0 or v > 1e12:
        await message.answer("out of range")
        return
    await users_repo.update_settings(user.telegram_id, {"max_loss_per_day": v})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:cooldown_seconds")
async def set_cd_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.cooldown_seconds)
    await cb.message.answer("send cooldown seconds (0 disables)")
    await cb.answer()


@router.message(SettingsFlow.cooldown_seconds)
async def set_cd_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        v = int(txt)
    except Exception:
        await message.answer("invalid integer")
        return
    if v < 0 or v > 3600:
        await message.answer("out of range")
        return
    await users_repo.update_settings(user.telegram_id, {"cooldown_seconds": v})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.callback_query(F.data == "set:max_consecutive_losses")
async def set_mcl_start(cb: CallbackQuery, state: FSMContext):
    user = await _ensure_user_from_callback(cb)
    if user.blocked:
        await cb.message.answer("access denied")
        await cb.answer()
        return
    await state.set_state(SettingsFlow.max_consecutive_losses)
    await cb.message.answer("send max consecutive losses (0 disables)")
    await cb.answer()


@router.message(SettingsFlow.max_consecutive_losses)
async def set_mcl_value(message: Message, state: FSMContext):
    user = await _ensure_user_from_message(message)
    if user is None:
        return
    if user.blocked:
        await message.answer("access denied")
        await state.clear()
        return
    txt = (message.text or "").strip()
    try:
        v = int(txt)
    except Exception:
        await message.answer("invalid integer")
        return
    if v < 0 or v > 1000:
        await message.answer("out of range")
        return
    await users_repo.update_settings(user.telegram_id, {"max_consecutive_losses": v})
    await state.clear()
    await message.answer("saved", reply_markup=settings_menu())


@router.message(Command("global_on"))
async def global_on(message: Message):
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("access denied")
        return
    await system_repo.set_global_trading_enabled(True)
    await message.answer("global trading enabled")


@router.message(Command("global_off"))
async def global_off(message: Message):
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("access denied")
        return
    await system_repo.set_global_trading_enabled(False)
    await message.answer("global trading disabled")


@router.message(Command("admin_users"))
async def admin_users(message: Message):
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("access denied")
        return
    users = await users_repo.list_users(limit=50)
    if not users:
        await message.answer("no users")
        return
    lines = []
    for u in users:
        lines.append(f"{u.telegram_id} @{u.username or '-'} blocked={u.blocked} trading={u.settings.trading_enabled}")
    await message.answer("\n".join(lines))


@router.message(Command("admin_block"))
async def admin_block(message: Message):
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("access denied")
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("usage: /admin_block <telegram_id>")
        return
    try:
        tid = int(parts[1])
    except Exception:
        await message.answer("invalid telegram_id")
        return
    ok = await users_repo.set_blocked(tid, True)
    await message.answer("blocked" if ok else "user not found")


@router.message(Command("admin_unblock"))
async def admin_unblock(message: Message):
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("access denied")
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("usage: /admin_unblock <telegram_id>")
        return
    try:
        tid = int(parts[1])
    except Exception:
        await message.answer("invalid telegram_id")
        return
    ok = await users_repo.set_blocked(tid, False)
    await message.answer("unblocked" if ok else "user not found")

