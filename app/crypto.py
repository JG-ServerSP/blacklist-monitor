from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_settings = get_settings()
_fernet = Fernet(_settings.fernet_key.encode() if isinstance(_settings.fernet_key, str) else _settings.fernet_key)


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet.encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    return _fernet.decrypt(token.encode()).decode()


def safe_decrypt(token: str) -> str | None:
    """Like decrypt() but never raises: returns None on any failure (corrupted
    ciphertext, rotated key, malformed value). Callers can then skip that one
    value instead of letting a single bad row 500 the whole request."""
    try:
        return decrypt(token)
    except InvalidToken:
        return None
    except Exception:
        return None
