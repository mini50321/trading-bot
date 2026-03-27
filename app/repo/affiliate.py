from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ReturnDocument

from app.config import get_settings
from app.db.mongo import mongo


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AffiliateRepo:
    async def record_event(self, payload: dict[str, Any]) -> None:
        doc = {"created_at": _now(), "payload": payload}
        await mongo.db.affiliate_events.insert_one(doc)

    async def upsert_account_by_email(self, email: str, patch: dict[str, Any]) -> None:
        e = (email or "").strip().lower()
        if not e:
            return
        await mongo.db.affiliate_accounts.update_one(
            {"email": e},
            {"$set": {"email": e, **patch, "updated_at": _now()}},
            upsert=True,
        )

    async def link_telegram_id(self, email: str, telegram_id: int) -> None:
        e = (email or "").strip().lower()
        if not e:
            return
        await mongo.db.affiliate_accounts.update_one(
            {"email": e},
            {"$set": {"telegram_id": int(telegram_id), "updated_at": _now()}},
            upsert=True,
        )

    async def clear_telegram_link(self, telegram_id: int) -> None:
        await mongo.db.affiliate_accounts.update_many(
            {"telegram_id": int(telegram_id)},
            {"$unset": {"telegram_id": ""}, "$set": {"updated_at": _now()}},
        )

    async def get_account_by_email(self, email: str) -> dict[str, Any] | None:
        e = (email or "").strip().lower()
        if not e:
            return None
        return await mongo.db.affiliate_accounts.find_one({"email": e})

    async def add_pending_tokens(self, email: str, delta: int) -> None:
        if delta <= 0:
            return
        e = (email or "").strip().lower()
        if not e:
            return
        await mongo.db.affiliate_accounts.update_one(
            {"email": e},
            {"$inc": {"pending_tokens": int(delta)}, "$set": {"updated_at": _now()}},
            upsert=True,
        )

    async def take_pending_tokens(self, email: str) -> int:
        e = (email or "").strip().lower()
        if not e:
            return 0
        doc = await mongo.db.affiliate_accounts.find_one_and_update(
            {"email": e},
            {"$set": {"pending_tokens": 0, "updated_at": _now()}},
            return_document=ReturnDocument.BEFORE,
        )
        if not doc:
            return 0
        return max(0, int(doc.get("pending_tokens") or 0))

    async def is_trading_allowed(self, telegram_id: int) -> tuple[bool, str | None]:
        """
        When affiliate_gate_required: require postback, matching Telegram link, and (if
        affiliate_email_confirm_required) a stored email-confirmation postback for that email.
        """
        if not get_settings().affiliate_gate_required:
            return True, None

        from app.repo.credentials import credentials_repo

        creds = await credentials_repo.get_credentials(telegram_id)
        if creds is None:
            return False, "connect_required"

        email = creds[0].strip().lower()
        if not email:
            return False, "connect_required"

        doc = await mongo.db.affiliate_accounts.find_one({"email": email})
        if doc is None:
            return False, "affiliate_email_unknown"

        if doc.get("telegram_id") != int(telegram_id):
            return False, "affiliate_telegram_unlinked"

        if not doc.get("postback_received"):
            return False, "affiliate_postback_pending"

        if get_settings().affiliate_email_confirm_required:
            confirmed = bool(doc.get("email_confirmed") or doc.get("email_confirmed_at"))
            if not confirmed:
                return False, "email_not_confirmed"

        return True, None

    async def describe_status(self, telegram_id: int) -> str:
        s = get_settings()
        if not s.affiliate_gate_required:
            return "verified (affiliate_gate_off)"

        from app.repo.credentials import credentials_repo

        creds = await credentials_repo.get_credentials(telegram_id)
        if creds is None:
            return "not_verified:connect_required"
        email = creds[0].strip().lower()
        doc = await mongo.db.affiliate_accounts.find_one({"email": email}) if email else None
        if doc is None:
            return "not_verified:affiliate_email_unknown"
        if doc.get("telegram_id") != int(telegram_id):
            return "not_verified:affiliate_telegram_unlinked"
        if not doc.get("postback_received"):
            return "not_verified:affiliate_postback_pending"
        if s.affiliate_email_confirm_required:
            if not (doc.get("email_confirmed") or doc.get("email_confirmed_at")):
                return "not_verified:email_not_confirmed"
        return "verified"


affiliate_repo = AffiliateRepo()

