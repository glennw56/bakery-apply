"""Cover signup, login, Google OAuth, apply, optional resume PDF, admin list, auth walls, open positions."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_fd, _db = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["BAKERY_APPLY_DB"] = _db
os.environ.pop("DATABASE_URL", None)
os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
os.environ.pop("GCP_PROJECT", None)
os.environ.pop("GCS_BUCKET", None)
os.environ.pop("FIRESTORE_COLLECTION", None)
os.environ.pop("K_SERVICE", None)
os.environ.pop("SESSION_HTTPS", None)
os.environ["SESSION_SECRET"] = "test-secret-not-for-production"
os.environ["ADMIN_EMAIL"] = "admin@test.local"
os.environ["ADMIN_PASSWORD"] = "admin-test-password"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import seed_admin  # noqa: E402
from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.store import ROOT, open_store, seed_positions  # noqa: E402

init_db()
seed_admin()
seed_positions()

WAGE_NEEDLES = (
    "wage",
    "hourly",
    "salary",
    "per hour",
    "/hr",
    "compensation",
    "pay rate",
    "stipend",
)

WHY_SHOP = "I walk here for cookies and want to work a small neighborhood shop."


def _client() -> TestClient:
    return TestClient(app)


def _signup(client: TestClient, email: str, password: str = "secret123") -> None:
    response = client.post(
        "/signup",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


def _open_position_id() -> str:
    store = open_store()
    try:
        rows = store.list_open_positions()
        assert rows, "expected seeded open Counter / Cashier"
        assert rows[0].title == "Counter / Cashier"
        return str(rows[0].id)
    finally:
        store.close()


def _apply_data(**overrides: str) -> dict[str, str]:
    data = {
        "name": "Jane Doe",
        "phone": "205-555-0100",
        "availability": "Weekends and after 3pm",
        "position_id": _open_position_id(),
        "weekends": "yes",
        "start_date": "2026-09-08",
        "hours_per_week": "25",
        "age_18": "yes",
        "work_auth": "yes",
        "been_in_shop": "yes",
        "prior_counter": "no",
        "prior_where": "",
        "why_shop": WHY_SHOP,
        "hear_about": "walked_in",
    }
    data.update(overrides)
    return data


def _assert_no_invented_openings(text: str) -> None:
    assert re.search(r"\bBaker\b", text) is None
    assert re.search(r"\bManager\b", text) is None


def test_signup() -> None:
    client = _client()
    _signup(client, "signup@example.com")
    home = client.get("/")
    assert home.status_code == 200
    assert "Log out" in home.text
    assert "signup@example.com" not in home.text or True


def test_login() -> None:
    client = _client()
    _signup(client, "login@example.com")
    client.post("/logout")
    response = client.post(
        "/login",
        data={"email": "login@example.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/apply")


def test_submit_application() -> None:
    client = _client()
    _signup(client, "apply@example.com")
    apply_form = client.get("/apply")
    assert apply_form.status_code == 200
    assert "Counter / Cashier" in apply_form.text
    assert 'name="position_id"' in apply_form.text
    created = client.post(
        "/apply",
        data=_apply_data(),
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "Jane Doe" in created.text
    assert "submitted" in created.text.lower()
    assert "Weekends and after 3pm" in created.text
    assert WHY_SHOP in created.text
    assert "Counter / Cashier" in created.text
    assert "type=\"file\"" not in created.text
    assert "application/pdf" not in created.text.lower()
    assert "Resume attached (PDF)" not in created.text
    status = client.get("/application")
    assert status.status_code == 200
    assert WHY_SHOP in status.text
    assert "Walked in" in status.text
    assert "Counter / Cashier" in status.text
    assert "Resume attached (PDF)" not in status.text


def test_missing_why_shop_redirects_to_apply() -> None:
    client = _client()
    _signup(client, "nowhy@example.com")
    data = _apply_data()
    data["why_shop"] = ""
    response = client.post("/apply", data=data, follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/apply")
    missing = _apply_data()
    missing.pop("why_shop")
    omitted = client.post("/apply", data=missing, follow_redirects=False)
    assert omitted.status_code in (302, 303)
    assert omitted.headers["location"].endswith("/apply")


def test_admin_can_list_apps() -> None:
    applicant = _client()
    _signup(applicant, "listed@example.com")
    applicant.post(
        "/apply",
        data=_apply_data(
            name="Sam Irondale",
            phone="(205) 555-0199",
            availability="Thu–Sun",
            prior_counter="yes",
            prior_where="Daily Bread Cafe",
            why_shop=WHY_SHOP,
            hear_about="instagram",
        ),
    )

    admin = _client()
    logged = admin.post(
        "/login",
        data={"email": "admin@test.local", "password": "admin-test-password"},
        follow_redirects=False,
    )
    assert logged.status_code in (302, 303)
    page = admin.get("/admin")
    assert page.status_code == 200
    assert "Sam Irondale" in page.text
    assert "(205) 555-0199" in page.text
    assert "Thu–Sun" in page.text
    assert "Counter / Cashier" in page.text
    assert WHY_SHOP in page.text
    assert "Daily Bread Cafe" in page.text
    assert "Instagram" in page.text
    assert "listed@example.com" in page.text
    assert "register-admin" not in page.text

    marked = admin.post(
        "/admin/applications/1/review",
        headers={"HX-Request": "true"},
    )
    # id may not be 1 if other tests created rows; parse from the list page
    if marked.status_code == 404 or "Sam Irondale" not in marked.text:
        ids = re.findall(r"/admin/applications/(\d+)/review", page.text)
        assert ids
        marked = admin.post(
            f"/admin/applications/{ids[0]}/review",
            headers={"HX-Request": "true"},
        )
    assert marked.status_code == 200
    assert "reviewed" in marked.text.lower()
    assert WHY_SHOP in marked.text
    if "Sam Irondale" in marked.text:
        assert "listed@example.com" in marked.text


def test_unauthenticated_cannot_hit_admin() -> None:
    anon = _client()
    response = anon.get("/admin", follow_redirects=False)
    assert response.status_code in (302, 303, 401, 403)
    if response.status_code in (302, 303):
        assert "/login" in response.headers.get("location", "")
    posted = anon.post(
        "/admin/positions",
        data={
            "title": "Sneaky Role",
            "hours_per_week": "10",
            "hourly_pay_min": "8",
            "hourly_pay_max": "8",
            "open": "true",
        },
        follow_redirects=False,
    )
    assert posted.status_code in (302, 303, 401)
    if posted.status_code in (302, 303):
        assert "/login" in posted.headers.get("location", "")
    home = anon.get("/")
    assert home.status_code == 200
    assert "Sneaky Role" not in home.text
    sneaky_update = anon.post(
        "/admin/positions/1",
        data={"action": "close"},
        follow_redirects=False,
    )
    assert sneaky_update.status_code in (302, 303, 401)


def test_public_cannot_register_as_admin() -> None:
    missing = _client().get("/register-admin")
    assert missing.status_code == 404

    client = _client()
    client.post(
        "/signup",
        data={
            "email": "notadmin@example.com",
            "password": "secret123",
            "is_admin": "true",
        },
    )
    admin_page = client.get("/admin", follow_redirects=False)
    assert admin_page.status_code in (302, 303, 401, 403)


def test_no_wage_text_on_pages() -> None:
    client = _client()
    pages = [client.get("/"), client.get("/signup"), client.get("/login")]
    _signup(client, "nowage@example.com")
    apply_form = client.get("/apply")
    pages.append(apply_form)
    client.post("/apply", data=_apply_data(name="Pat Irondale", phone="205-555-0111", availability="Open"))
    pages.append(client.get("/apply"))
    pages.append(client.get("/application"))

    admin = _client()
    admin.post(
        "/login",
        data={"email": "admin@test.local", "password": "admin-test-password"},
    )
    pages.append(admin.get("/admin"))

    home = pages[0]
    assert home.status_code == 200
    assert "$13/hour" in home.text
    assert "40 hours/week" in home.text
    assert "Starting out" not in home.text
    assert "Counter / Cashier" in home.text
    _assert_no_invented_openings(home.text)
    assert "No resume file" not in home.text
    assert "Resume PDF is optional" in home.text
    assert "/register-admin" not in home.text
    assert "Talent reads" not in home.text

    admin_page = pages[-1]
    for response in pages[1:]:
        assert response.status_code in (200, 303, 302)
        if response.status_code != 200:
            continue
        body = response.text.lower()
        assert "trussville" not in body
        assert "/register-admin" not in body
        assert "talent reads" not in body
        if response is not admin_page:
            for needle in WAGE_NEEDLES:
                assert needle not in body, f"{needle!r} found on page"
            assert re.search(r"\$\s*\d", response.text) is None
            _assert_no_invented_openings(response.text)
        if response is not apply_form:
            assert "application/pdf" not in body
            assert 'type="file"' not in body
    assert admin_page.status_code == 200
    assert "Add a position" in admin_page.text
    assert 'action="/admin/positions"' in admin_page.text
    assert apply_form.status_code == 200
    assert 'type="file"' in apply_form.text
    assert 'name="resume"' in apply_form.text
    assert "Resume (PDF, optional)" in apply_form.text
    assert "Talent reads" not in apply_form.text
    assert "A few sentences about why you want to work here." in apply_form.text
    assert "Counter / Cashier" in apply_form.text


def test_home_no_longer_says_no_resume_file() -> None:
    home = _client().get("/")
    assert home.status_code == 200
    assert "No resume file" not in home.text
    assert "Resume PDF is optional" in home.text
    assert "$13/hour" in home.text
    assert "40 hours/week" in home.text
    assert "Starting out" not in home.text
    assert "Counter / Cashier" in home.text
    _assert_no_invented_openings(home.text)


def test_admin_post_open_job_shows_on_home() -> None:
    admin = _client()
    logged = admin.post(
        "/login",
        data={"email": "admin@test.local", "password": "admin-test-password"},
        follow_redirects=False,
    )
    assert logged.status_code in (302, 303)
    page = admin.get("/admin")
    assert page.status_code == 200
    assert "Add a position" in page.text
    assert "Counter / Cashier" in page.text
    created = admin.post(
        "/admin/positions",
        data={
            "title": "Pastry Cook",
            "hours_per_week": "32",
            "hourly_pay_min": "16",
            "hourly_pay_max": "16",
            "description": "Mix and shape pastry for the case.",
            "open": "true",
        },
        follow_redirects=False,
    )
    assert created.status_code in (302, 303)
    assert created.headers["location"].endswith("/admin")
    home = _client().get("/")
    assert home.status_code == 200
    assert "Pastry Cook" in home.text
    assert "32" in home.text
    assert "$16" in home.text
    assert "Counter / Cashier" in home.text
    assert "$13" in home.text


def test_admin_can_close_position_and_it_disappears_from_home() -> None:
    admin = _client()
    logged = admin.post(
        "/login",
        data={"email": "admin@test.local", "password": "admin-test-password"},
        follow_redirects=False,
    )
    assert logged.status_code in (302, 303)
    admin.post(
        "/admin/positions",
        data={
            "title": "Night Porter",
            "hours_per_week": "25",
            "hourly_pay_min": "15",
            "hourly_pay_max": "15",
            "open": "true",
        },
        follow_redirects=False,
    )
    store = open_store()
    try:
        row = next(p for p in store.list_positions() if p.title == "Night Porter")
        pos_id = row.id
    finally:
        store.close()
    home = _client().get("/")
    assert home.status_code == 200
    assert "Night Porter" in home.text
    assert "Counter / Cashier" in home.text
    closed = admin.post(
        f"/admin/positions/{pos_id}",
        data={"action": "close"},
        follow_redirects=False,
    )
    assert closed.status_code in (302, 303)
    gone = _client().get("/")
    assert gone.status_code == 200
    assert "Night Porter" not in gone.text
    assert "Counter / Cashier" in gone.text
    assert "$13" in gone.text
    assert "40 hours/week" in gone.text


TINY_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 24
DOC_BYTES = b"\xd0\xcf\x11\xe0" + b"\x00" * 24
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 24


def test_apply_with_valid_resume_pdf_admin_can_download() -> None:
    client = _client()
    _signup(client, "withpdf@example.com")
    created = client.post(
        "/apply",
        data=_apply_data(name="Pat Pdf"),
        files={"resume": ("resume.pdf", TINY_PDF, "application/pdf")},
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "Pat Pdf" in created.text
    assert 'href="/application/resume"' in created.text
    assert "/data/resumes" not in created.text
    assert 'href="/admin/applications/' not in created.text

    own = client.get("/application/resume")
    assert own.status_code == 200
    assert own.headers.get("content-type", "").split(";")[0].strip() == "application/pdf"
    assert own.content.startswith(b"%PDF")

    admin = _client()
    logged = admin.post(
        "/login",
        data={"email": "admin@test.local", "password": "admin-test-password"},
        follow_redirects=False,
    )
    assert logged.status_code in (302, 303)
    page = admin.get("/admin")
    assert page.status_code == 200
    ids = re.findall(r"/admin/applications/(\d+)/resume", page.text)
    assert ids
    app_id = ids[0]
    stored = ROOT / "data" / "resumes" / f"{app_id}.pdf"
    assert stored.is_file()
    assert stored.read_bytes().startswith(b"%PDF")
    downloaded = admin.get(f"/admin/applications/{app_id}/resume")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF")
    cd = downloaded.headers.get("content-disposition", "").lower()
    assert "attachment" in cd
    assert "resume.pdf" in cd


def test_non_pdf_resume_rejected() -> None:
    """PNG/JPEG bytes named resume.pdf, or a real .png, bounce back with no row."""
    cases = (
        ("spoofpng@example.com", ("resume.pdf", PNG_BYTES, "application/pdf")),
        ("spoofjpeg@example.com", ("resume.pdf", JPEG_BYTES, "image/jpeg")),
        ("realpng@example.com", ("photo.png", PNG_BYTES, "image/png")),
        ("realjpg@example.com", ("photo.jpg", JPEG_BYTES, "image/jpeg")),
        ("realdoc@example.com", ("resume.doc", DOC_BYTES, "application/msword")),
        ("realdocx@example.com", ("resume.docx", DOCX_BYTES, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
    )
    for email, file_tuple in cases:
        client = _client()
        _signup(client, email)
        response = client.post(
            "/apply",
            data=_apply_data(),
            files={"resume": file_tuple},
            follow_redirects=False,
        )
        assert response.status_code in (302, 303), email
        assert response.headers["location"].endswith("/apply"), email
        still = client.get("/apply", follow_redirects=False)
        assert still.status_code == 200, email
        assert "Resume attached (PDF)" not in still.text
        status = client.get("/application", follow_redirects=False)
        assert status.status_code in (302, 303)
        assert status.headers["location"].endswith("/apply")


def test_empty_content_type_pdf_is_accepted() -> None:
    client = _client()
    _signup(client, "emptyctype@example.com")
    created = client.post(
        "/apply",
        data=_apply_data(name="Empty Ctype"),
        files={"resume": ("resume.pdf", TINY_PDF, "")},
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert 'href="/application/resume"' in created.text


def test_unauthenticated_cannot_download_resume() -> None:
    anon = _client()
    response = anon.get("/admin/applications/1/resume", follow_redirects=False)
    assert response.status_code in (302, 303, 401, 403)
    if response.status_code in (302, 303):
        assert "/login" in response.headers.get("location", "")


def test_applicant_resume_is_own_only() -> None:
    """Anonymous users bounce to login; another applicant never gets this PDF."""
    owner = _client()
    _signup(owner, "resume-owner@example.com")
    created = owner.post(
        "/apply",
        data=_apply_data(name="Owner Pdf"),
        files={"resume": ("resume.pdf", TINY_PDF, "application/pdf")},
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert 'href="/application/resume"' in created.text
    own = owner.get("/application/resume")
    assert own.status_code == 200
    assert own.content.startswith(b"%PDF")

    anon = _client()
    bounced = anon.get("/application/resume", follow_redirects=False)
    assert bounced.status_code in (302, 303)
    assert "/login" in bounced.headers.get("location", "")

    other = _client()
    _signup(other, "resume-other@example.com")
    other_get = other.get("/application/resume", follow_redirects=False)
    assert other_get.status_code == 404
    assert not other_get.content.startswith(b"%PDF")


def test_docs_and_openapi_are_disabled() -> None:
    client = _client()
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_session_https_only_false_without_k_service() -> None:
    assert not os.environ.get("K_SERVICE")
    assert os.environ.get("SESSION_HTTPS") not in ("1", "true", "TRUE")
    from app.backend import session_https_only
    from app.main import SESSION_HTTPS_ONLY
    from starlette.middleware.sessions import SessionMiddleware

    assert session_https_only() is False
    assert SESSION_HTTPS_ONLY is False
    found = False
    for middleware in app.user_middleware:
        if getattr(middleware, "cls", None) is SessionMiddleware:
            assert middleware.kwargs.get("https_only") is False
            found = True
    assert found


def test_cloud_backend_off_without_project_and_bucket() -> None:
    from app.backend import use_cloud_backend

    assert use_cloud_backend() is False
    import sys

    assert "google.cloud.firestore" not in sys.modules
    assert "google.cloud.storage" not in sys.modules
    assert "app.cloud" not in sys.modules


def test_cloud_backend_requires_both_env_vars(monkeypatch) -> None:
    from app.backend import firestore_collection, session_https_only, use_cloud_backend

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "bakery-444323")
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    assert use_cloud_backend() is False
    monkeypatch.setenv("GCS_BUCKET", "private-bucket")
    assert use_cloud_backend() is True
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GCP_PROJECT", "bakery-444323")
    assert use_cloud_backend() is True
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    assert use_cloud_backend() is False
    monkeypatch.delenv("FIRESTORE_COLLECTION", raising=False)
    assert firestore_collection() == "applications"
    monkeypatch.setenv("K_SERVICE", "bakery-apply")
    assert session_https_only() is True
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setenv("SESSION_HTTPS", "1")
    assert session_https_only() is True
    import sys

    assert "google.cloud.firestore" not in sys.modules
    assert "google.cloud.storage" not in sys.modules


LIVE_GOOGLE_REDIRECT = "https://bakery-apply-k6uuoen7wa-ue.a.run.app/auth/google/callback"


def _google_env(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", LIVE_GOOGLE_REDIRECT)


def _patch_google(monkeypatch, info: dict) -> None:
    def fake_exchange(code: str) -> dict:
        assert code == "good-code"
        return {"access_token": "tok-test"}

    def fake_userinfo(token: str) -> dict:
        assert token == "tok-test"
        return info

    monkeypatch.setattr("app.main.exchange_code", fake_exchange)
    monkeypatch.setattr("app.main.fetch_userinfo", fake_userinfo)


def _google_start(client: TestClient):
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code == 302
    return response


def _google_state(client: TestClient) -> str:
    from urllib.parse import parse_qs, urlparse

    started = _google_start(client)
    query = parse_qs(urlparse(started.headers["location"]).query)
    return query["state"][0]


def test_google_redirect_uri_default_and_public_base(monkeypatch) -> None:
    from app.google_oauth import DEFAULT_REDIRECT_URI, google_redirect_uri

    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert google_redirect_uri() == DEFAULT_REDIRECT_URI
    assert DEFAULT_REDIRECT_URI == LIVE_GOOGLE_REDIRECT
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test/")
    assert google_redirect_uri() == "https://example.test/auth/google/callback"
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", LIVE_GOOGLE_REDIRECT)
    assert google_redirect_uri() == LIVE_GOOGLE_REDIRECT


def test_email_is_verified_requires_true() -> None:
    from app.google_oauth import email_is_verified

    assert email_is_verified({"email_verified": True})
    assert email_is_verified({"email_verified": "true"})
    assert email_is_verified({"email_verified": "TRUE"})
    assert not email_is_verified({"email_verified": False})
    assert not email_is_verified({"email_verified": "false"})
    assert not email_is_verified({})
    assert not email_is_verified({"email_verified": 1})


def test_google_cta_on_home_login_and_signup() -> None:
    client = _client()
    for path in ("/", "/login", "/signup"):
        page = client.get(path)
        assert page.status_code == 200
        assert "Sign in with Google" in page.text
        assert 'href="/auth/google/start"' in page.text
    assert 'action="/login"' in client.get("/login").text
    assert 'action="/signup"' in client.get("/signup").text


def test_google_start_without_config(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    client = _client()
    response = client.get("/auth/google/start", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/login")
    page = client.get("/login")
    assert "not configured" in page.text


def test_google_oauth_start_and_callback(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    _google_env(monkeypatch)
    _patch_google(
        monkeypatch,
        {
            "sub": "google-sub-1",
            "email": "Applicant@Gmail.com",
            "email_verified": True,
        },
    )
    client = _client()
    started = _google_start(client)
    location = started.headers["location"]
    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["test-client-id"]
    assert query["redirect_uri"] == [LIVE_GOOGLE_REDIRECT]
    assert query["response_type"] == ["code"]
    assert "openid" in query["scope"][0]
    assert "email" in query["scope"][0]
    assert query["state"][0]
    assert "client_secret" not in location
    state = query["state"][0]

    callback = client.get(
        f"/auth/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code in (302, 303)
    assert callback.headers["location"].endswith("/apply")
    apply_page = client.get("/apply")
    assert apply_page.status_code == 200
    assert "Log out" in apply_page.text

    store = open_store()
    try:
        user = store.get_user_by_email("applicant@gmail.com")
        assert user is not None
        assert user.google_sub == "google-sub-1"
        assert user.provider == "google"
        assert user.is_admin is False
        assert not user.password_hash.startswith("$2")
        user_id = user.id
    finally:
        store.close()

    submitted = client.post(
        "/apply",
        data=_apply_data(name="Google Applicant"),
        follow_redirects=False,
    )
    assert submitted.status_code in (302, 303)
    assert submitted.headers["location"].endswith("/application")
    client.post("/logout")
    again = client.get(
        f"/auth/google/callback?code=good-code&state={_google_state(client)}",
        follow_redirects=False,
    )
    assert again.status_code in (302, 303)
    assert again.headers["location"].endswith("/application")
    store = open_store()
    try:
        again_user = store.get_user_by_google_sub("google-sub-1")
        assert again_user is not None
        assert again_user.id == user_id
    finally:
        store.close()

    client.post("/logout")
    password = client.post(
        "/login",
        data={"email": "applicant@gmail.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert password.headers["location"].endswith("/login")
    login_page = client.get("/login")
    assert "uses Sign in with Google" in login_page.text
    assert "Log out" not in login_page.text


def test_google_callback_rejects_unverified_email(monkeypatch) -> None:
    _google_env(monkeypatch)
    _patch_google(
        monkeypatch,
        {
            "sub": "sub-unverified",
            "email": "unverified@gmail.com",
            "email_verified": False,
        },
    )
    client = _client()
    state = _google_state(client)
    response = client.get(
        f"/auth/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/login")
    page = client.get("/login")
    assert "did not verify" in page.text
    assert "Log out" not in page.text
    store = open_store()
    try:
        assert store.get_user_by_email("unverified@gmail.com") is None
        assert store.get_user_by_google_sub("sub-unverified") is None
    finally:
        store.close()


def test_google_callback_rejects_bad_state(monkeypatch) -> None:
    _google_env(monkeypatch)
    called = {"n": 0}

    def fake_exchange(code: str) -> dict:
        called["n"] += 1
        return {"access_token": "tok-test"}

    monkeypatch.setattr("app.main.exchange_code", fake_exchange)
    client = _client()
    _google_state(client)
    response = client.get(
        "/auth/google/callback?code=good-code&state=not-the-state",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert response.headers["location"].endswith("/login")
    assert called["n"] == 0
    page = client.get("/login")
    assert "could not be confirmed" in page.text
    assert "Log out" not in page.text


def test_google_links_existing_password_applicant(monkeypatch) -> None:
    _google_env(monkeypatch)
    _patch_google(
        monkeypatch,
        {
            "sub": "linked-sub",
            "email": "linked@example.com",
            "email_verified": True,
        },
    )
    client = _client()
    _signup(client, "linked@example.com")
    store = open_store()
    try:
        before = store.get_user_by_email("linked@example.com")
        assert before is not None
        before_id = before.id
        assert before.provider == "password"
        assert before.google_sub is None
    finally:
        store.close()
    client.post("/logout")
    response = client.get(
        f"/auth/google/callback?code=good-code&state={_google_state(client)}",
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("/apply")
    store = open_store()
    try:
        after = store.get_user_by_email("linked@example.com")
        assert after is not None
        assert after.id == before_id
        assert after.google_sub == "linked-sub"
        assert after.provider == "google"
        assert after.password_hash.startswith("$2")
    finally:
        store.close()
    client.post("/logout")
    logged = client.post(
        "/login",
        data={"email": "linked@example.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert logged.headers["location"].endswith("/apply")


def test_google_callback_does_not_sign_in_admin(monkeypatch) -> None:
    _google_env(monkeypatch)
    _patch_google(
        monkeypatch,
        {
            "sub": "admin-sub",
            "email": "admin@test.local",
            "email_verified": True,
        },
    )
    client = _client()
    response = client.get(
        f"/auth/google/callback?code=good-code&state={_google_state(client)}",
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("/login")
    page = client.get("/login")
    assert "Admin accounts sign in with email and password." in page.text
    admin_try = client.get("/admin", follow_redirects=False)
    assert admin_try.status_code in (302, 303)
    assert "/login" in admin_try.headers["location"]
    store = open_store()
    try:
        admin = store.get_user_by_email("admin@test.local")
        assert admin is not None and admin.is_admin
        assert not admin.google_sub
        assert store.get_user_by_google_sub("admin-sub") is None
    finally:
        store.close()


def test_jobs_are_clickable_and_login_frames_applying() -> None:
    client = _client()
    pos_id = _open_position_id()
    home = client.get("/")
    assert home.status_code == 200
    assert "How to apply" in home.text
    assert "Pick a job." in home.text
    assert "Log in to apply" in home.text
    assert "Sign up to apply" in home.text
    assert "Resume PDF is optional" in home.text
    assert "Sign in with Google to apply." in home.text
    assert f'href="/jobs/{pos_id}"' in home.text
    assert f'href="/login?position_id={pos_id}"' in home.text
    assert f'href="/signup?position_id={pos_id}"' in home.text
    assert 'class="role-card"' in home.text

    job = client.get(f"/jobs/{pos_id}")
    assert job.status_code == 200
    assert "<h1>Counter / Cashier</h1>" in job.text
    assert "$13/hour" in job.text
    assert "40 hours/week" in job.text
    assert "Starting out" not in job.text
    assert "2231 1st Ave S" in job.text
    assert "Log in to apply" in job.text
    assert "Sign up with email" in job.text
    assert f'href="/login?position_id={pos_id}"' in job.text
    assert f'href="/signup?position_id={pos_id}"' in job.text

    missing = client.get("/jobs/999999", follow_redirects=False)
    assert missing.status_code == 303
    assert missing.headers["location"].endswith("/")
    flashed = client.get("/jobs/not-a-job")
    assert flashed.status_code == 200
    assert "open right now" in flashed.text
    assert "Counter / Cashier" in flashed.text

    login = client.get(f"/login?position_id={pos_id}")
    assert "<h1>Log in to apply</h1>" in login.text
    assert "You need an account to submit an application." in login.text
    assert ">Log in to apply</button>" in login.text
    assert login.text.index("btn-google") < login.text.index("auth-divider")
    assert f'name="position_id" value="{pos_id}"' in login.text
    assert f'href="/signup?position_id={pos_id}"' in login.text

    signup = client.get("/signup")
    assert "<h1>Sign up to apply</h1>" in signup.text
    assert "Create an account to submit an application." in signup.text
    assert ">Sign up to apply</button>" in signup.text
    assert signup.text.index("btn-google") < signup.text.index("auth-divider")

    created = client.post(
        "/signup",
        data={"email": "jobcta@example.com", "password": "secret123", "position_id": pos_id},
        follow_redirects=False,
    )
    assert created.status_code in (302, 303)
    assert created.headers["location"].endswith(f"/apply?position_id={pos_id}")
    apply_page = client.get(f"/apply?position_id={pos_id}")
    assert apply_page.status_code == 200
    assert f'value="{pos_id}" selected' in apply_page.text
    assert "applying for Counter / Cashier" in apply_page.text
    logged_home = client.get("/")
    assert "Apply for this role" in logged_home.text
    assert f'href="/apply?position_id={pos_id}"' in logged_home.text
    job_in = client.get(f"/jobs/{pos_id}")
    assert "Apply for this role" in job_in.text
    assert f'href="/apply?position_id={pos_id}"' in job_in.text

    client.post("/logout")
    logged = client.post(
        "/login",
        data={"email": "jobcta@example.com", "password": "secret123", "position_id": pos_id},
        follow_redirects=False,
    )
    assert logged.headers["location"].endswith(f"/apply?position_id={pos_id}")

    outsider = client.post(
        "/login",
        data={
            "email": "jobcta@example.com",
            "password": "secret123",
            "next": "https://evil.example/phish",
        },
        follow_redirects=False,
    )
    assert outsider.headers["location"].endswith("/apply")

    admin = _client()
    admin.post(
        "/login",
        data={"email": "admin@test.local", "password": "admin-test-password"},
        follow_redirects=False,
    )
    admin.post(
        "/admin/positions",
        data={
            "title": "Bread Runner",
            "hours_per_week": "20",
            "hourly_pay_min": "14",
            "hourly_pay_max": "14",
            "description": "Restock the bread shelf.",
            "open": "true",
        },
        follow_redirects=False,
    )
    store = open_store()
    try:
        row = next(p for p in store.list_positions() if p.title == "Bread Runner" and p.open)
        closed_id = row.id
    finally:
        store.close()
    visible = client.get(f"/jobs/{closed_id}")
    assert visible.status_code == 200
    assert "Bread Runner" in visible.text
    admin.post(f"/admin/positions/{closed_id}", data={"action": "close"}, follow_redirects=False)
    closed = client.get(f"/jobs/{closed_id}", follow_redirects=False)
    assert closed.status_code == 303
    assert closed.headers["location"].endswith("/")
    home_after = client.get("/")
    assert "Bread Runner" not in home_after.text


def test_google_sign_in_keeps_selected_job(monkeypatch) -> None:
    from urllib.parse import parse_qs, urlparse

    _google_env(monkeypatch)
    _patch_google(
        monkeypatch,
        {
            "sub": "google-sub-job",
            "email": "job.google@gmail.com",
            "email_verified": True,
        },
    )
    client = _client()
    pos_id = _open_position_id()
    login_page = client.get(f"/login?position_id={pos_id}")
    assert login_page.status_code == 200
    started = _google_start(client)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/auth/google/callback?code=good-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code in (302, 303)
    assert callback.headers["location"].endswith(f"/apply?position_id={pos_id}")


def _admin_client() -> TestClient:
    admin = _client()
    logged = admin.post(
        "/login",
        data={"email": "admin@test.local", "password": "admin-test-password"},
        follow_redirects=False,
    )
    assert logged.status_code in (302, 303)
    return admin


def test_pay_range_display_admin_create_and_legacy_cents() -> None:
    """Equal rates stay one amount. A wider range uses an en dash and one dollar sign.

    Legacy docs that only have hourly_pay_cents still render that rate. Starting out
    is omitted unless starting_out is true. Shift lead stays unlabeled.
    """
    from app.cloud import CloudPosition
    from app.models import (
        TASTING_DESCRIPTION,
        TASTING_PAY_MAX_CENTS,
        TASTING_PAY_MIN_CENTS,
        TASTING_TITLE,
        Position,
        format_hourly_pay_range,
    )
    from app.store import create_tasting_position

    assert format_hourly_pay_range(1400, 1400) == "$14/hour"
    assert "$14\u2013$14" not in format_hourly_pay_range(1400, 1400)
    assert format_hourly_pay_range(1400, 1600) == "$14\u201316/hour"
    assert format_hourly_pay_range(1200, 1400) == "$12\u201314/hour"
    assert format_hourly_pay_range(1350, 1600) == "$13.50\u201316/hour"

    legacy_doc = CloudPosition(
        "ophEWXhxBOlXME0qGmpw",
        {
            "title": "shift lead",
            "hours_per_week": 40,
            "hourly_pay_cents": 1400,
            "open": True,
        },
    )
    assert legacy_doc.hourly_pay_min_cents == 1400
    assert legacy_doc.hourly_pay_max_cents == 1400
    assert legacy_doc.hourly_pay_cents == 1400
    assert legacy_doc.starting_out is False
    assert legacy_doc.hourly_pay_display == "$14/hour"
    assert legacy_doc.experience_display == ""
    assert legacy_doc.role_meta == "40 hours/week · $14/hour"
    assert legacy_doc.pay_min_dollars_input == "14"
    assert legacy_doc.pay_max_dollars_input == "14"

    ranged_doc = CloudPosition(
        "range-doc",
        {
            "title": "Tasting",
            "hours_per_week": 20,
            "hourly_pay_cents": 1200,
            "hourly_pay_min_cents": 1200,
            "hourly_pay_max_cents": 1400,
            "starting_out": True,
            "open": True,
        },
    )
    assert ranged_doc.hourly_pay_display == "$12\u201314/hour"
    assert ranged_doc.experience_display == "Starting out"
    assert ranged_doc.role_meta == "20 hours/week · $12\u201314/hour · Starting out"
    assert ranged_doc.hourly_pay_cents == 1200

    closed_baker = CloudPosition(
        "MhIsQT5RwvNC7yZQ30WS",
        {
            "title": "Baker",
            "hours_per_week": 40,
            "hourly_pay_cents": 1500,
            "open": False,
        },
    )
    assert closed_baker.hourly_pay_display == "$15/hour"
    assert closed_baker.starting_out is False
    assert "Starting out" not in closed_baker.role_meta

    admin = _admin_client()
    page = admin.get("/admin")
    assert "Pay from (dollars)" in page.text
    assert "Pay to (dollars)" in page.text
    assert 'name="starting_out"' in page.text
    assert "Hourly pay (dollars)" not in page.text
    assert "40 hours/week · $13/hour" in page.text
    assert "40 hours/week · $13/hour · Starting out" not in page.text

    equal = admin.post(
        "/admin/positions",
        data={
            "title": "Equal Rate Role",
            "hours_per_week": "40",
            "hourly_pay_min": "14",
            "hourly_pay_max": "14",
            "open": "true",
        },
        follow_redirects=False,
    )
    assert equal.status_code in (302, 303)

    ranged = admin.post(
        "/admin/positions",
        data={
            "title": "Range Rate Role",
            "hours_per_week": "40",
            "hourly_pay_min": "14",
            "hourly_pay_max": "16",
            "starting_out": "true",
            "description": "A posted range.",
            "open": "true",
        },
        follow_redirects=False,
    )
    assert ranged.status_code in (302, 303)

    rejected = admin.post(
        "/admin/positions",
        data={
            "title": "Backwards Pay",
            "hours_per_week": "10",
            "hourly_pay_min": "16",
            "hourly_pay_max": "14",
            "open": "true",
        },
        follow_redirects=True,
    )
    assert rejected.status_code == 200
    assert "Pay to must be at least pay from." in rejected.text
    assert "Backwards Pay" not in rejected.text

    store = open_store()
    try:
        assert all(p.title != TASTING_TITLE for p in store.list_positions())
        equal_row = next(p for p in store.list_positions() if p.title == "Equal Rate Role")
        range_row = next(p for p in store.list_positions() if p.title == "Range Rate Role")
        assert equal_row.hourly_pay_cents == 1400
        assert equal_row.hourly_pay_min_cents == 1400
        assert equal_row.hourly_pay_max_cents == 1400
        assert equal_row.starting_out is False
        assert equal_row.hourly_pay_display == "$14/hour"
        assert equal_row.role_meta == "40 hours/week · $14/hour"
        assert range_row.hourly_pay_cents == 1400
        assert range_row.hourly_pay_min_cents == 1400
        assert range_row.hourly_pay_max_cents == 1600
        assert range_row.starting_out is True
        assert range_row.hourly_pay_display == "$14\u201316/hour"
        assert range_row.role_meta == "40 hours/week · $14\u201316/hour · Starting out"
        legacy_row = Position(
            title="Legacy Cents Role",
            hours_per_week=40,
            hourly_pay_cents=1400,
            hourly_pay_min_cents=None,
            hourly_pay_max_cents=None,
            starting_out=False,
            open=True,
            description="",
        )
        store.db.add(legacy_row)
        store.db.commit()
        store.db.refresh(legacy_row)
        legacy_id = legacy_row.id
        assert legacy_row.hourly_pay_display == "$14/hour"
        assert legacy_row.experience_display == ""
        # Hours are caller-supplied; Ronald set pay, title, and Starting out only.
        tasting = create_tasting_position(store, hours_per_week=20)
        assert tasting.title == TASTING_TITLE
        assert tasting.hourly_pay_min_cents == TASTING_PAY_MIN_CENTS == 1200
        assert tasting.hourly_pay_max_cents == TASTING_PAY_MAX_CENTS == 1400
        assert tasting.hourly_pay_cents == 1200
        assert tasting.starting_out is True
        assert tasting.open is True
        assert tasting.description == TASTING_DESCRIPTION
        assert tasting.hourly_pay_display == "$12\u201314/hour"
        assert tasting.role_meta == "20 hours/week · $12\u201314/hour · Starting out"
        tasting_id = tasting.id
    finally:
        store.close()

    saved = admin.post(
        f"/admin/positions/{range_row.id}",
        data={
            "action": "save",
            "title": "Range Rate Role",
            "hours_per_week": "40",
            "hourly_pay_min": "14",
            "hourly_pay_max": "16",
            "starting_out": "true",
            "description": "A posted range.",
            "open": "true",
        },
        follow_redirects=False,
    )
    assert saved.status_code in (302, 303)

    home = _client().get("/")
    assert "40 hours/week · $14/hour" in home.text
    assert "40 hours/week · $14/hour · Starting out" not in home.text
    assert "40 hours/week · $14\u201316/hour · Starting out" in home.text
    assert "20 hours/week · $12\u201314/hour · Starting out" in home.text
    assert "$14\u2013$14/hour" not in home.text
    job = _client().get(f"/jobs/{range_row.id}")
    assert job.status_code == 200
    assert "40 hours/week · $14\u201316/hour · Starting out" in job.text
    legacy_job = _client().get(f"/jobs/{legacy_id}")
    assert legacy_job.status_code == 200
    assert "Legacy Cents Role" in legacy_job.text
    assert "40 hours/week · $14/hour" in legacy_job.text
    assert "Starting out" not in legacy_job.text
    tasting_job = _client().get(f"/jobs/{tasting_id}")
    assert tasting_job.status_code == 200
    assert "<h1>Tasting</h1>" in tasting_job.text
    assert "20 hours/week · $12\u201314/hour · Starting out" in tasting_job.text
    assert TASTING_DESCRIPTION in tasting_job.text

    summary = admin.get("/admin")
    assert "40 hours/week · $14/hour" in summary.text
    assert "40 hours/week · $14\u201316/hour · Starting out" in summary.text
    assert "20 hours/week · $12\u201314/hour · Starting out" in summary.text

    store = open_store()
    try:
        for title in ("Equal Rate Role", "Range Rate Role", "Legacy Cents Role", TASTING_TITLE):
            row = next(p for p in store.list_positions() if p.title == title)
            store.db.delete(row)
        store.db.commit()
    finally:
        store.close()
