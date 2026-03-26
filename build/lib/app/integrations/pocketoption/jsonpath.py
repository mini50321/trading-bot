from __future__ import annotations

from typing import Any


def get_by_dotted_path(data: Any, path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur
