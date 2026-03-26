from __future__ import annotations

from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.db.mongo import mongo
from app.domain.execution import StoredSignal, WebhookSignalIn


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SignalsRepo:
    async def store(self, s: WebhookSignalIn) -> tuple[bool, StoredSignal]:
        created_at = s.created_at or _now()
        doc = StoredSignal(
            source=s.source,
            signal_id=s.signal_id,
            symbol=s.symbol.strip().lower(),
            direction=s.direction,
            created_at=created_at,
            payload=s.payload or {},
        )
        try:
            await mongo.db.signals.insert_one(doc.model_dump())
            return True, doc
        except DuplicateKeyError:
            existing = await mongo.db.signals.find_one({"source": s.source, "signal_id": s.signal_id})
            if existing is None:
                return False, doc
            return False, StoredSignal.model_validate(existing)


signals_repo = SignalsRepo()

