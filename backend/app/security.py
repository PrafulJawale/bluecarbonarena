
"""Authentication & authorization.

Strategy: short-lived JWT bearer tokens (HS256) issued by the API, stored in
memory (never localStorage) by the frontend; session recovery via re-login only.
Server-side revocation is supported through a per-user `token_version` claim:
bumping the version (logout / admin deactivation / role change) invalidates all
previously issued tokens for that user. Tokens also expire after
ACCESS_TOKEN_MINUTES regardless.

Passwords: Argon2id hashing (argon2-cffi default). No credentials are ever logged.
"""
import jwt
import uuid
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.profiles import RFC_9106_LOW_MEMORY
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User

ph = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)  # Argon2id
bearer = HTTPBearer(auto_error=False)


def hash_pw(p: str) -> str:
    return ph.hash(p)


def verify_pw(p: str, h: str) -> bool:
    try:
        return ph.verify(h, p)
    except Exception:
        return False


def create_token(u: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode(
        {"sub": str(u.id), "role": u.role, "tv": u.token_version or 0,
         "jti": uuid.uuid4().hex, "exp": exp},
        settings.secret_key, algorithm="HS256")


def get_current_user(cred=Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(cred.credentials, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired, please log in again")
    except Exception:
        raise HTTPException(401, "Invalid or expired token")
    u = db.get(User, int(payload["sub"]))
    if not u or not u.is_active:
        raise HTTPException(401, "User inactive")
    if (u.token_version or 0) != payload.get("tv", -1):
        raise HTTPException(401, "Session invalidated, please log in again")
    return u


def require(*roles):
    """Role gate. Admin passes any gate except gates that explicitly exclude it
    (gates list roles verbatim; admin is included implicitly unless 'no_admin=True')."""
    def dep(u: User = Depends(get_current_user)):
        if u.role not in roles and not (u.role == "admin"):
            raise HTTPException(403, "Forbidden for your role")
        return u
    return dep
