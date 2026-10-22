"""
src/services/auth_service.py — Authentication and authorisation service.

Handles:
- Password hashing and verification.
- JWT token creation and validation.
- User registration and login.
- Role enforcement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from src.core.config import settings
from src.db.models import User, UserRole

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password Utilities ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── JWT Utilities ─────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


# ── User Queries ──────────────────────────────────────────────────────────────

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Return user if credentials are valid, else None."""
    user = get_user_by_email(db, email)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def register_user(
    db: Session,
    email: str,
    password: str,
    full_name: str,
    role: UserRole = UserRole.LEARNER,
) -> User:
    """
    Register a new user.

    Raises:
        ValueError: If email is already registered.
    """
    email = email.lower().strip()
    if get_user_by_email(db, email):
        raise ValueError(f"Email {email!r} is already registered.")
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── Token from Request ────────────────────────────────────────────────────────

def get_current_user_from_token(token: str, db: Session) -> User:
    """
    Decode a JWT token and return the corresponding active user.

    Raises:
        ValueError: If token is invalid, expired, or user not found/inactive.
    """
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise ValueError("Invalid token: missing subject.")
    except JWTError as exc:
        raise ValueError(f"Invalid or expired token: {exc}") from exc

    user = get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise ValueError("User not found or account is deactivated.")
    return user
