"""FastAPI @Controller: public hiring page, signup/login, apply form, admin list.

Each @app.get / @app.post is a request mapping. Jinja templates are the view;
HTMX swaps the admin row when an application is marked reviewed.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
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
from app.backend import session_https_only
from app.db import init_db
from app.models import (
    HEAR_ABOUT_CHOICES,
    HEAR_ABOUT_SLUGS,
    STATUS_SUBMITTED,
    YES_NO,
)
from app.store import get_store, seed_positions

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
CHICAGO = ZoneInfo("America/Chicago")

SHOP_NAME = "Sunshine's Bakery"
SHOP_ADDRESS = "2231 1st Ave S, Irondale AL 35210"
SHOP_PHONE = "(205) 602-3485"
MAX_RESUME_BYTES = 5 * 1024 * 1024


def session_secret() -> str:
    return os.environ.get("SESSION_SECRET") or "local-dev-change-me"


SESSION_HTTPS_ONLY = session_https_only()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_admin()
    seed_positions()
    yield


app = FastAPI(
    title="Sunshine's Bakery Apply",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="bakery_apply",
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
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
templates.env.globals["hear_about_choices"] = HEAR_ABOUT_CHOICES


def _ctx(request: Request, user, **extra):
    flash = request.session.pop("flash", None)
    data = {
        "request": request,
        "user": user,
        "flash": flash,
    }
    data.update(extra)
    return data


def render(request: Request, name: str, user, **extra):
    """Starlette 1.x: TemplateResponse(request, name, context)."""
    return templates.TemplateResponse(request, name, _ctx(request, user, **extra))


def _flash(request: Request, message: str) -> None:
    request.session["flash"] = message


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


def _parse_hours(raw: str) -> int | None:
    raw = (raw or "").strip()
    try:
        hours = int(raw)
    except ValueError:
        return None
    if hours < 0:
        return None
    return hours


def _parse_pay_cents(raw: str) -> int | None:
    """Admin form is dollars (13 or 13.50) stored as cents."""
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    raw = raw.replace("/hour", "").replace("/hr", "").strip()
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _is_open_value(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "on", "yes")


# --- Public hiring page -------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home(request: Request, store=Depends(get_store)):
    user = get_current_user(request, store)
    open_positions = store.list_open_positions()
    return render(request, "index.html", user, open_positions=open_positions)


# --- Auth (applicant signup + login). No public admin register. ---------------


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, store=Depends(get_store)):
    user = get_current_user(request, store)
    if user is not None:
        return _redirect("/apply" if not user.is_admin else "/admin")
    return render(request, "signup.html", user)


@app.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    is_admin: str | None = Form(None),  # ignored — public cannot register as admin
    store=Depends(get_store),
):
    _ = is_admin  # never honored
    email_n = normalize_email(email)
    if not email_n or "@" not in email_n:
        _flash(request, "Enter a valid email.")
        return _redirect("/signup")
    if len(password) < 8:
        _flash(request, "Password must be at least 8 characters.")
        return _redirect("/signup")
    existing = store.get_user_by_email(email_n)
    if existing is not None:
        _flash(request, "That email already has an account. Log in instead.")
        return _redirect("/login")
    user = store.create_user(email_n, hash_password(password), is_admin=False)
    login_user(request, user)
    return _redirect("/apply")


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, store=Depends(get_store)):
    user = get_current_user(request, store)
    if user is not None:
        return _redirect("/admin" if user.is_admin else "/apply")
    return render(request, "login.html", user)


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    store=Depends(get_store),
):
    email_n = normalize_email(email)
    user = store.get_user_by_email(email_n)
    if user is None or not verify_password(password, user.password_hash):
        _flash(request, "Email or password did not match.")
        return _redirect("/login")
    login_user(request, user)
    if user.is_admin:
        return _redirect("/admin")
    if store.get_application_for_user(user.id) is not None:
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
    user=Depends(require_login),
    store=Depends(get_store),
):
    if user.is_admin:
        return _redirect("/admin")
    existing = store.get_application_for_user(user.id)
    if existing is not None:
        return _redirect("/application")
    open_positions = store.list_open_positions()
    return render(request, "apply.html", user, open_positions=open_positions)


def _yes_no(value: str | None) -> str:
    return (value or "").strip().lower()


def _optional_resume_bytes(upload: UploadFile | None) -> bytes | None:
    """Return PDF bytes, None if omitted, or raise ValueError if not a valid PDF."""
    if upload is None:
        return None
    filename = (upload.filename or "").strip()
    if not filename:
        return None
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Resume must be a PDF.")
    ctype = (upload.content_type or "").strip()
    if ";" in ctype:
        ctype = ctype.split(";", 1)[0].strip()
    if ctype and ctype.lower() != "application/pdf":
        raise ValueError("Resume must be a PDF.")
    blob = upload.file.read(MAX_RESUME_BYTES + 1)
    if len(blob) > MAX_RESUME_BYTES:
        raise ValueError("Resume must be 5 MB or smaller.")
    if not blob.startswith(b"%PDF"):
        raise ValueError("Resume must be a PDF.")
    return blob


@app.post("/apply")
def apply_submit(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    availability: str = Form(...),
    position_id: str = Form(""),
    weekends: str = Form(""),
    start_date: str = Form(""),
    hours_per_week: str = Form(""),
    age_18: str = Form(""),
    work_auth: str = Form(""),
    been_in_shop: str = Form(""),
    prior_counter: str = Form(""),
    prior_where: str = Form(""),
    why_shop: str = Form(""),
    hear_about: str = Form(""),
    resume: UploadFile | None = File(None),
    user=Depends(require_login),
    store=Depends(get_store),
):
    if user.is_admin:
        return _redirect("/admin")
    existing = store.get_application_for_user(user.id)
    if existing is not None:
        return _redirect("/application")
    name = name.strip()
    phone = phone.strip()
    availability = availability.strip()
    weekends = _yes_no(weekends)
    start_date = start_date.strip()
    hours_per_week = hours_per_week.strip()
    age_18 = _yes_no(age_18)
    work_auth = _yes_no(work_auth)
    been_in_shop = _yes_no(been_in_shop)
    prior_counter = _yes_no(prior_counter)
    prior_where = prior_where.strip()
    why_shop = why_shop.strip()
    hear_about = hear_about.strip()
    if not name or not phone or not availability:
        _flash(request, "Name, phone, and availability are required.")
        return _redirect("/apply")
    yn_ok = all(
        v in YES_NO
        for v in (weekends, age_18, work_auth, been_in_shop, prior_counter)
    )
    if not yn_ok or not start_date or not hours_per_week or hear_about not in HEAR_ABOUT_SLUGS:
        _flash(request, "Please answer all of the screening questions.")
        return _redirect("/apply")
    if not why_shop:
        _flash(request, "Please tell us why this shop — a few sentences.")
        return _redirect("/apply")
    if prior_counter == "yes" and not prior_where:
        _flash(request, "If you have bakery, coffee, or cafe counter work, say where.")
        return _redirect("/apply")
    if prior_counter != "yes":
        prior_where = ""
    position = store.get_position(position_id)
    if position is None or not position.open:
        _flash(request, "Pick an open position.")
        return _redirect("/apply")
    try:
        resume_bytes = _optional_resume_bytes(resume)
    except ValueError as exc:
        _flash(request, str(exc))
        return _redirect("/apply")
    app_row = store.create_application(
        user_id=user.id,
        name=name,
        phone=phone,
        availability=availability,
        role=position.title,
        position_id=position.id,
        weekends=weekends,
        start_date=start_date,
        hours_per_week=hours_per_week,
        age_18=age_18,
        work_auth=work_auth,
        been_in_shop=been_in_shop,
        prior_counter=prior_counter,
        prior_where=prior_where,
        why_shop=why_shop,
        hear_about=hear_about,
        status=STATUS_SUBMITTED,
        submitted_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    if resume_bytes:
        store.save_resume(app_row, resume_bytes)
    return _redirect("/application")


@app.get("/application", response_class=HTMLResponse)
def my_application(
    request: Request,
    user=Depends(require_login),
    store=Depends(get_store),
):
    if user.is_admin:
        return _redirect("/admin")
    existing = store.get_application_for_user(user.id)
    if existing is None:
        return _redirect("/apply")
    return render(request, "application.html", user, application=existing)


# --- Admin: seeded from env, not public self-serve ----------------------------


@app.get("/admin", response_class=HTMLResponse)
def admin_list(
    request: Request,
    admin=Depends(require_admin),
    store=Depends(get_store),
):
    rows = store.list_applications()
    positions = store.list_positions()
    return render(
        request,
        "admin/index.html",
        admin,
        applications=rows,
        positions=positions,
    )


@app.post("/admin/applications/{app_id}/review", response_class=HTMLResponse)
def admin_mark_reviewed(
    app_id: str,
    request: Request,
    admin=Depends(require_admin),
    store=Depends(get_store),
):
    row = store.get_application(app_id)
    if row is None:
        if _is_htmx(request):
            return HTMLResponse("", status_code=404)
        _flash(request, "Application not found.")
        return _redirect("/admin")
    row = store.mark_reviewed(row)
    if _is_htmx(request):
        return render(request, "admin/_row.html", admin, item=row)
    return _redirect("/admin")


@app.get("/admin/applications/{app_id}/resume")
def admin_download_resume(
    app_id: str,
    admin=Depends(require_admin),
    store=Depends(get_store),
):
    _ = admin
    row = store.get_application(app_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    response = store.resume_response(row)
    if response is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return response


@app.get("/admin/positions")
def admin_positions_redirect(admin=Depends(require_admin)):
    _ = admin
    return _redirect("/admin")


@app.post("/admin/positions")
def admin_create_position(
    request: Request,
    title: str = Form(""),
    hours_per_week: str = Form(""),
    hourly_pay: str = Form(""),
    description: str = Form(""),
    open: str | None = Form(None),
    admin=Depends(require_admin),
    store=Depends(get_store),
):
    _ = admin
    title = title.strip()
    hours = _parse_hours(hours_per_week)
    cents = _parse_pay_cents(hourly_pay)
    if not title or hours is None or cents is None:
        _flash(request, "Title, hours/week, and hourly pay (dollars) are required.")
        return _redirect("/admin")
    store.create_position(
        title=title,
        hours_per_week=hours,
        hourly_pay_cents=cents,
        open=_is_open_value(open),
        description=description.strip(),
    )
    _flash(request, "Position added.")
    return _redirect("/admin")


@app.post("/admin/positions/{pos_id}")
def admin_update_position(
    pos_id: str,
    request: Request,
    title: str = Form(""),
    hours_per_week: str = Form(""),
    hourly_pay: str = Form(""),
    description: str = Form(""),
    open: str | None = Form(None),
    action: str = Form(""),
    admin=Depends(require_admin),
    store=Depends(get_store),
):
    _ = admin
    row = store.get_position(pos_id)
    if row is None:
        _flash(request, "Position not found.")
        return _redirect("/admin")
    action = (action or "").strip().lower()
    if action == "close":
        store.update_position(row, open=False)
        _flash(request, "Position closed. It is hidden from the public hiring page.")
        return _redirect("/admin")
    if action == "reopen":
        store.update_position(row, open=True)
        _flash(request, "Position reopened.")
        return _redirect("/admin")
    title = title.strip()
    hours = _parse_hours(hours_per_week)
    cents = _parse_pay_cents(hourly_pay)
    if not title or hours is None or cents is None:
        _flash(request, "Title, hours/week, and hourly pay (dollars) are required.")
        return _redirect("/admin")
    store.update_position(
        row,
        title=title,
        hours_per_week=hours,
        hourly_pay_cents=cents,
        open=_is_open_value(open),
        description=description.strip(),
    )
    _flash(request, "Position saved.")
    return _redirect("/admin")
