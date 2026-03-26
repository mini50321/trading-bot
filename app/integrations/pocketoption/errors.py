from __future__ import annotations


class PocketOptionHttpError(RuntimeError):
    def __init__(self, *, op: str, status: int, body: bytes | None = None) -> None:
        self.op = op
        self.status = int(status)
        self.body = body or b""
        super().__init__(f"{op} failed: {self.status}")

