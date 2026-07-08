from cryptography.fernet import Fernet

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
