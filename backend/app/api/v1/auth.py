from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, get_current_user
from app.config import get_settings
from app.core.rate_limit import login_failures_by_client_account, login_failures_by_ip, registrations_by_ip
from app.core.security import create_access_token, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.auth import AccountDelete, Token, UserCreate, UserLogin, UserRead
from app.services.auth_service import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    authenticate_user,
    delete_account,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

TOO_MANY = HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts. Try again later.")


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _start_session(response: Response, user: User) -> Token:
    token = create_access_token(user.id)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=settings.jwt_expire_minutes * 60, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path="/",
    )
    # The token is also returned for API clients; the web app relies on the cookie only.
    return Token(access_token=token)


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, request: Request, response: Response, db: Session = Depends(get_db)) -> Token:
    if registrations_by_ip.blocked(_client(request)):
        raise TOO_MANY
    registrations_by_ip.hit(_client(request))
    try:
        user = register_user(db, data)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    return _start_session(response, user)


@router.post("/login", response_model=Token)
def login(data: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)) -> Token:
    ip_key = _client(request)
    account_key = f"{ip_key}|{data.email.lower()}"
    if login_failures_by_client_account.blocked(account_key) or login_failures_by_ip.blocked(ip_key):
        raise TOO_MANY
    try:
        user = authenticate_user(db, data.email, data.password)
    except InvalidCredentialsError:
        login_failures_by_client_account.hit(account_key)
        login_failures_by_ip.hit(ip_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    login_failures_by_client_account.reset(account_key)
    return _start_session(response, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, samesite="lax", httponly=True)


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/delete-account", status_code=status.HTTP_204_NO_CONTENT)
def remove_account(
    data: AccountDelete,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanently deletes the account, its CVs (including stored files), jobs,
    applications and connected email account. Requires the current password."""
    if not verify_password(data.password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password is incorrect")
    delete_account(db, current_user)
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, samesite="lax", httponly=True)
