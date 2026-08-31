"""FastAPI @Controller: public hiring page, signup/login, apply form, admin list.

Each @app.get / @app.post is a request mapping. Jinja templates are the view;
HTMX swaps the admin row when an application is marked reviewed.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import (
    LoginRedirect,
    get_current_user,
    hash_password,
    login_redirect_handler,
    login_user,
    logout_user,
    normalize_email,
    require_admin,
    require_login,
    seed_admin,
    verify_password,
)
from app.db import get_db, init_db
from app.models import (
    ROLE_COUNTER,
    STATUS_REVIEWED,
    STATUS_SUBMITTED,
    Application,
    User,
)

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
CHICAGO = ZoneInfo("America/Chicago")

SHOP_NAME = "Sunshine's Bakery"
SHOP_ADDRESS = "2231 1st Ave S, Irondale AL 35210"
SHOP_PHONE = "(205) 602-3485"
LIVE_ROLE = ROLE_COUNTER


def session_secret() -> str:
    return os.environ.get("SESSION_SECRET") or "local-dev-change-me"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_admin()
    yield


app = FastAPI(title="Sunshine's Bakery Apply", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="bakery_apply",
    same_site="lax",
    https_only=False,
)
app.add_exception_handler(LoginRedirect, login_redirect_handler)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def chicago_stamp(dt: datetime) -> str:
    """Wall clock in America/Chicago, e.g. Aug 30, 2026 8:21 PM."""
    local = _as_utc(dt).astimezone(CHICAGO)
    return local.strftime("%b %-d, %Y %-I:%M %p")


templates.env.globals["chicago_stamp"] = chicago_stamp
templates.env.globals["shop_name"] = SHOP_NAME
templates.env.globals["shop_address"] = SHOP_ADDRESS
templates.env.globals["shop_phone"] = SHOP_PHONE
templates.env.globals["live_role"] = LIVE_ROLE


def _ctx(request: Request, user: User | None, **extra):
    flash = request.session.pop("flash", None)
    data = {
        "request": request,
        "user": user,
        "flash": flash,
        "role_options": [LIVE_ROLE],
    }
    data.update(extra)
    return data


def render(request: Request, name: str, user: User | None, **extra):
    """Starlette 1.x: TemplateResponse(request, name, context)."""
    return templates.TemplateResponse(request, name, _ctx(request, user, **extra))


def _flash(request: Request, message: str) -> None:
    request.session["flash"] = message


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


# --- Public hiring page -------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return render(request, "index.html", user)


# --- Auth (applicant signup + login). No public admin register. ---------------


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is not None:
        return _redirect("/apply" if not user.is_admin else "/admin")
    return render(request, "signup.html", user)


@app.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    is_admin: str | None = Form(None),  # ignored — public cannot register as admin
    db: Session = Depends(get_db),
):
    _ = is_admin  # never honored
    email_n = normalize_email(email)
    if not email_n or "@" not in email_n:
        _flash(request, "Enter a valid email.")
        return _redirect("/signup")
    if len(password) < 8:
        _flash(request, "Password must be at least 8 characters.")
        return _redirect("/signup")
    existing = db.scalar(select(User).where(User.email == email_n))
    if existing is not None:
        _flash(request, "That email already has an account. Log in instead.")
        return _redirect("/login")
    user = User(email=email_n, password_hash=hash_password(password), is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    login_user(request, user)
    return _redirect("/apply")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is not None:
        return _redirect("/admin" if user.is_admin else "/apply")
    return render(request, "login.html", user)


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email_n = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email_n))
    if user is None or not verify_password(password, user.password_hash):
        _flash(request, "Email or password did not match.")
        return _redirect("/login")
    login_user(request, user)
    if user.is_admin:
        return _redirect("/admin")
    if user.application is not None:
        return _redirect("/application")
    return _redirect("/apply")


@app.post("/logout")
def logout(request: Request):
    logout_user(request)
    return _redirect("/")


# --- Applicant apply + status -------------------------------------------------


@app.get("/apply", response_class=HTMLResponse)
def apply_form(
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    if user.is_admin:
        return _redirect("/admin")
    existing = db.scalar(select(Application).where(Application.user_id == user.id))
    if existing is not None:
        return _redirect("/application")
    return render(request, "apply.html", user)


@app.post("/apply")
def apply_submit(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    availability: str = Form(...),
    role: str = Form(LIVE_ROLE),
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    if user.is_admin:
        return _redirect("/admin")
    existing = db.scalar(select(Application).where(Application.user_id == user.id))
    if existing is not None:
        return _redirect("/application")
    name = name.strip()
    phone = phone.strip()
    availability = availability.strip()
    if not name or not phone or not availability:
        _flash(request, "Name, phone, and availability are required.")
        return _redirect("/apply")
    # Only the live Counter / Cashier role is accepted in v1.
    _ = role
    app_row = Application(
        user_id=user.id,
        name=name,
        phone=phone,
        availability=availability,
        role=LIVE_ROLE,
        status=STATUS_SUBMITTED,
        submitted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(app_row)
    db.commit()
    return _redirect("/application")


@app.get("/application", response_class=HTMLResponse)
def my_application(
    request: Request,
    user: User = Depends(require_login),
    db: Session = Depends(get_db),
):
    if user.is_admin:
        return _redirect("/admin")
    existing = db.scalar(select(Application).where(Application.user_id == user.id))
    if existing is None:
        return _redirect("/apply")
    return render(request, "application.html", user, application=existing)


# --- Admin: seeded from env, not public self-serve ----------------------------


@app.get("/admin", response_class=HTMLResponse)
def admin_list(
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Application).order_by(Application.submitted_at.desc())).all()
    return render(request, "admin/index.html", admin, applications=rows)


@app.post("/admin/applications/{app_id}/review", response_class=HTMLResponse)
def admin_mark_reviewed(
    app_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(Application, app_id)
    if row is None:
        if _is_htmx(request):
            return HTMLResponse("", status_code=404)
        _flash(request, "Application not found.")
        return _redirect("/admin")
    row.status = STATUS_REVIEWED
    row.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    if _is_htmx(request):
        return render(request, "admin/_row.html", admin, item=row)
    return _redirect("/admin")
