from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import UserCreate


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def register_user(db: Session, data: UserCreate) -> User:
    existing = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    if existing is not None:
        raise EmailAlreadyRegisteredError

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_account(db: Session, user: User) -> None:
    from app.storage.file_storage import delete_stored_file
    paths = [resume.file_path for resume in user.resumes]
    db.delete(user)
    db.commit()
    for path in paths:
        delete_stored_file(path)


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    # Hash even for unknown emails so response time doesn't reveal which accounts exist.
    if not verify_password(password, user.hashed_password if user else _DUMMY_HASH) or user is None:
        raise InvalidCredentialsError
    return user


_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")
