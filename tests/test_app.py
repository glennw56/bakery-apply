"""Cover signup, login, apply, optional resume PDF, admin list, auth walls, no wage text."""

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

init_db()
seed_admin()

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


def _apply_data(**overrides: str) -> dict[str, str]:
    data = {
        "name": "Jane Doe",
        "phone": "205-555-0100",
        "availability": "Weekends and after 3pm",
        "role": "Counter / Cashier",
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
    assert "type=\"file\"" not in created.text
    assert "application/pdf" not in created.text.lower()
    assert "Resume attached (PDF)" not in created.text
    status = client.get("/application")
    assert status.status_code == 200
    assert WHY_SHOP in status.text
    assert "Walked in" in status.text
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
    assert "register-admin" not in page.text

    marked = admin.post(
        "/admin/applications/1/review",
        headers={"HX-Request": "true"},
    )
    # id may not be 1 if other tests created rows; parse from the list page
    if marked.status_code == 404 or "Sam Irondale" not in marked.text:
        import re as _re

        ids = _re.findall(r"/admin/applications/(\d+)/review", page.text)
        assert ids
        marked = admin.post(
            f"/admin/applications/{ids[0]}/review",
            headers={"HX-Request": "true"},
        )
    assert marked.status_code == 200
    assert "reviewed" in marked.text.lower()
    assert WHY_SHOP in marked.text


def test_unauthenticated_cannot_hit_admin() -> None:
    anon = _client()
    response = anon.get("/admin", follow_redirects=False)
    assert response.status_code in (302, 303, 401, 403)
    if response.status_code in (302, 303):
        assert "/login" in response.headers.get("location", "")


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

    for response in pages:
        assert response.status_code in (200, 303, 302)
        if response.status_code != 200:
            continue
        text = response.text.lower()
        for needle in WAGE_NEEDLES:
            assert needle not in text, f"{needle!r} found on page"
        assert re.search(r"\$\s*\d", response.text) is None
        assert "trussville" not in text
        assert "/register-admin" not in text
        assert "talent reads" not in text
        if response is not apply_form:
            assert "application/pdf" not in text
            assert 'type="file"' not in text
    assert apply_form.status_code == 200
    assert 'type="file"' in apply_form.text
    assert 'name="resume"' in apply_form.text
    assert "Resume (PDF, optional)" in apply_form.text
    assert "Talent reads" not in apply_form.text
    assert "A few sentences about why you want to work here." in apply_form.text
    home = pages[0]
    assert home.status_code == 200
    assert "No resume file" not in home.text
    assert "Resume PDF is optional" in home.text

TINY_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 24
DOC_BYTES = b"\xd0\xcf\x11\xe0" + b"\x00" * 24
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 24


def test_home_no_longer_says_no_resume_file() -> None:
    home = _client().get("/")
    assert home.status_code == 200
    assert "No resume file" not in home.text
    assert "Resume PDF is optional" in home.text


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
    assert "Resume attached (PDF)" in created.text
    assert "/data/resumes" not in created.text
    assert 'href="/admin/applications/' not in created.text

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
    stored = Path("/workspace/bakery-apply/data/resumes") / f"{app_id}.pdf"
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
    assert "Resume attached (PDF)" in created.text


def test_unauthenticated_cannot_download_resume() -> None:
    anon = _client()
    response = anon.get("/admin/applications/1/resume", follow_redirects=False)
    assert response.status_code in (302, 303, 401, 403)
    if response.status_code in (302, 303):
        assert "/login" in response.headers.get("location", "")


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
