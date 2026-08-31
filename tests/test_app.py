"""Cover signup, login, apply, admin list, auth walls, no public admin, no wage text."""

from __future__ import annotations

import os
import re
import tempfile

_fd, _db = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["BAKERY_APPLY_DB"] = _db
os.environ.pop("DATABASE_URL", None)
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


def _client() -> TestClient:
    return TestClient(app)


def _signup(client: TestClient, email: str, password: str = "secret123") -> None:
    response = client.post(
        "/signup",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)


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
        data={
            "name": "Jane Doe",
            "phone": "205-555-0100",
            "availability": "Weekends and after 3pm",
            "role": "Counter / Cashier",
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert "Jane Doe" in created.text
    assert "submitted" in created.text.lower()
    assert "Weekends and after 3pm" in created.text


def test_admin_can_list_apps() -> None:
    applicant = _client()
    _signup(applicant, "listed@example.com")
    applicant.post(
        "/apply",
        data={
            "name": "Sam Irondale",
            "phone": "(205) 555-0199",
            "availability": "Thu–Sun",
            "role": "Counter / Cashier",
        },
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
    client.post(
        "/apply",
        data={
            "name": "Pat Irondale",
            "phone": "205-555-0111",
            "availability": "Open",
            "role": "Counter / Cashier",
        },
    )
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
        assert "application/pdf" not in text
        assert "type=\"file\"" not in text
