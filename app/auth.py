"""Password hashes and session user lookup. Admin is seeded from env, not public signup."""

from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SESSION_USER_KEY = "user_id"


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def seed_admin() -> None:
    """Create or update the env admin (ADMIN_EMAIL + ADMIN_PASSWORD) with is_admin=true."""
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    email = normalize_email(email)
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email))
        hashed = hash_password(password)
        if user is None:
            user = User(email=email, password_hash=hashed, is_admin=True)
            db.add(user)
        else:
            user.password_hash = hashed
            user.is_admin = True
        db.commit()
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    return db.get(User, int(user_id))


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


class LoginRedirect(Exception):
    """Raised to bounce anonymous users to /login (HTML, not JSON 401)."""

    def __init__(self, next_path: str = "/") -> None:
        self.next_path = next_path


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if user is None:
        raise LoginRedirect(str(request.url.path))
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if user is None:
        raise LoginRedirect("/admin")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def login_redirect_handler(_request: Request, exc: LoginRedirect) -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


def login_user(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = user.id


def logout_user(request: Request) -> None:
    request.session.clear()
