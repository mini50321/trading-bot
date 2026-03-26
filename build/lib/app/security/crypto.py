from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _fernet_from_master_key(master_key: str) -> Fernet:
    digest = hashlib.sha256(master_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_text(master_key: str, plaintext: str) -> str:
    f = _fernet_from_master_key(master_key)
    token = f.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(master_key: str, token: str) -> str:
    f = _fernet_from_master_key(master_key)
    data = f.decrypt(token.encode("utf-8"))
    return data.decode("utf-8")

