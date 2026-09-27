"""Google OAuth 2.0 authorization-code flow for applicant sign-in.

Start stores a random `state` in the session and sends the browser to Google.
The callback checks that state (CSRF), exchanges the code, and reads the
OpenID userinfo document. `email_verified` must be true. Tokens are not stored.
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

import httpx

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Authorized redirect URI for the live Cloud Run service. Override with
# GOOGLE_REDIRECT_URI, or with PUBLIC_BASE_URL + /auth/google/callback.
DEFAULT_REDIRECT_URI = (
    "https://bakery-apply-k6uuoen7wa-ue.a.run.app/auth/google/callback"
)

OAUTH_STATE_SESSION_KEY = "google_oauth_state"


class GoogleOAuthError(Exception):
    """Token exchange or userinfo failed. Safe to show a generic message."""


def google_client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "").strip()


def google_client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()


def google_configured() -> bool:
    return bool(google_client_id() and google_client_secret())


def google_redirect_uri() -> str:
    explicit = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"{base}/auth/google/callback"
    return DEFAULT_REDIRECT_URI


def new_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def oauth_states_match(expected: object, got: object) -> bool:
    if not isinstance(expected, str) or not isinstance(got, str):
        return False
    if not expected or not got:
        return False
    return secrets.compare_digest(expected, got)


def build_authorize_url(state: str) -> str:
    query = urlencode(
        {
            "client_id": google_client_id(),
            "redirect_uri": google_redirect_uri(),
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"{GOOGLE_AUTH_URL}?{query}"


def email_is_verified(info: dict) -> bool:
    """True only when Google says the address is verified.

    Userinfo sends a JSON boolean. A string "true" is accepted so a proxy
    that stringifies the claim still works. Missing, false, and "false" do not.
    """
    value = info.get("email_verified")
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() == "true":
        return True
    return False


def exchange_code(code: str) -> dict:
    """Trade an authorization code for tokens. Raises GoogleOAuthError."""
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": google_client_id(),
                "client_secret": google_client_secret(),
                "redirect_uri": google_redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise GoogleOAuthError("token request failed") from exc
    if response.status_code != 200:
        raise GoogleOAuthError("token rejected")
    try:
        body = response.json()
    except ValueError as exc:
        raise GoogleOAuthError("token response was not JSON") from exc
    if not isinstance(body, dict) or not body.get("access_token"):
        raise GoogleOAuthError("no access token")
    return body


def fetch_userinfo(access_token: str) -> dict:
    """Read the verified identity for this access token."""
    try:
        response = httpx.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise GoogleOAuthError("userinfo failed") from exc
    if response.status_code != 200:
        raise GoogleOAuthError("userinfo rejected")
    try:
        body = response.json()
    except ValueError as exc:
        raise GoogleOAuthError("userinfo was not JSON") from exc
    if not isinstance(body, dict):
        raise GoogleOAuthError("userinfo was not an object")
    return body
