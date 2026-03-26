from __future__ import annotations

import logging
import re
from typing import Any


_WS = re.compile(r"\s+")

logger = logging.getLogger("app")


def configure_logging(*, level: str = "INFO") -> None:
    """Idempotent basic logging for API/bot processes."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(getattr(logging, (level or "INFO").upper(), logging.INFO))
        return
    logging.basicConfig(
        level=getattr(logging, (level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _fmt_val(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\n", " ").replace("\r", " ")
    s = _WS.sub(" ", s).strip()
    if len(s) > 400:
        s = s[:397] + "..."
    return s


def log_event(name: str, **fields: Any) -> None:
    """Stable key=value log line for grep/structured ingestion (no extra deps)."""
    tail = " ".join(f"{k}={_fmt_val(fields[k])}" for k in sorted(fields))
    logger.info("event=%s %s", name, tail)


def log_warning(name: str, **fields: Any) -> None:
    tail = " ".join(f"{k}={_fmt_val(fields[k])}" for k in sorted(fields))
    logger.warning("event=%s %s", name, tail)


def log_exception(name: str, exc: BaseException, **fields: Any) -> None:
    tail = " ".join(f"{k}={_fmt_val(fields[k])}" for k in sorted(fields))
    logger.exception("event=%s exc=%s %s", name, type(exc).__name__, tail)
