from __future__ import annotations

import base64
import hashlib
import secrets


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
        p=SCRYPT_P, dklen=DKLEN,
    )
    return "$".join(
        (
            "scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )
    )


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=_decode(salt), n=int(n), r=int(r),
            p=int(p), dklen=len(_decode(expected)),
        )
        return secrets.compare_digest(digest, _decode(expected))
    except (ValueError, TypeError):
        return False
