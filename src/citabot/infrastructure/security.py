"""Password hashing with scrypt from the standard library."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Work factor: 2**14 iterations, 16 MB of memory, about 50 ms per hash on a laptop.
_N, _R, _P = 2**14, 8, 1
_KEY_BYTES = 32
_SALT_BYTES = 16
_SCHEME = "scrypt"

# Stored for accounts that cannot sign in with a password. It never verifies.
UNUSABLE_PASSWORD = "!"


class ScryptHasher:
    """Stores `scrypt$n$r$p$salt$key`, so the work factor can be raised later
    without invalidating the hashes that already exist."""

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(_SALT_BYTES)
        key = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_BYTES)
        return f"{_SCHEME}${_N}${_R}${_P}${_b64(salt)}${_b64(key)}"

    def verify(self, password: str, stored: str) -> bool:
        try:
            scheme, n, r, p, salt, key = stored.split("$")
            if scheme != _SCHEME:
                return False
            expected = base64.b64decode(key)
            actual = hashlib.scrypt(
                password.encode(),
                salt=base64.b64decode(salt),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=len(expected),
            )
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual, expected)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()
