"""CV file storage. Files are encrypted at rest with RESUME_ENCRYPTION_KEY (".enc" suffix).
Files saved before encryption was introduced remain readable as plain files."""
import uuid
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import get_settings

settings = get_settings()


@lru_cache
def _fernet() -> Fernet:
    if not settings.resume_encryption_key:
        raise RuntimeError("RESUME_ENCRYPTION_KEY is not configured")
    return Fernet(settings.resume_encryption_key.encode())


def _storage_dir() -> Path:
    path = Path(settings.file_storage_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_encrypted_file(content: bytes, suffix: str) -> str:
    dest_path = _storage_dir() / f"{uuid.uuid4()}{suffix}.enc"
    dest_path.write_bytes(_fernet().encrypt(content))
    return str(dest_path)


def read_stored_file(path: str) -> bytes:
    data = Path(path).read_bytes()
    return _fernet().decrypt(data) if path.endswith(".enc") else data


def delete_stored_file(path: str | None) -> None:
    """Remove a stored CV file; only paths inside the storage directory are touched."""
    if not path:
        return
    target = Path(path).resolve()
    if _storage_dir() in target.parents:
        target.unlink(missing_ok=True)
