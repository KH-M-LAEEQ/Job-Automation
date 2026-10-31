from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User

SESSION_COOKIE = "applypilot_session"
# Browsers can't add this header to a cross-site request without a CORS preflight, which
# only the configured frontend origin passes - so it guards cookie sessions against CSRF.
CSRF_HEADER = "x-requested-with"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    request: Request,
    bearer: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = bearer
    if token is None:
        token = request.cookies.get(SESSION_COOKIE)
        if token and request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing request header")
    if not token:
        raise credentials_error

    user_id = decode_access_token(token)
    if user_id is None:
        raise credentials_error

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error

    return user
