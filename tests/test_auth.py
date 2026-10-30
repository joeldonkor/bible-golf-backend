"""Registration, sign-in, token refresh and sign-out."""

import pytest
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

pytestmark = pytest.mark.django_db


def test_register_then_use_the_returned_token(api):
    registered = api.post(
        "/api/auth/register/",
        {"email": "ruth@example.com", "password": "testpass123", "displayName": "Ruth"},
        format="json",
    ).json()

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {registered['tokens']['access']}")
    me = api.get("/api/auth/me/")
    assert me.status_code == 200
    assert me.json()["email"] == "ruth@example.com"


def test_email_is_normalised_and_unique(api):
    first = api.post(
        "/api/auth/register/",
        {"email": "Ruth@Example.com", "password": "testpass123", "displayName": "Ruth"},
        format="json",
    )
    assert first.status_code == 201
    assert first.json()["user"]["email"] == "ruth@example.com"

    second = api.post(
        "/api/auth/register/",
        {"email": "ruth@example.com", "password": "testpass123", "displayName": "Ruth"},
        format="json",
    )
    assert second.status_code == 400
    assert "email" in second.json()


def test_a_short_password_is_rejected_the_way_the_client_expects(api):
    """The client's zod schema says 6+; the server must agree, not surprise it."""
    response = api.post(
        "/api/auth/register/",
        {"email": "ruth@example.com", "password": "short", "displayName": "Ruth"},
        format="json",
    )
    assert response.status_code == 400
    assert "password" in response.json()


def test_bad_credentials_do_not_reveal_whether_the_account_exists(api, host):
    unknown = api.post(
        "/api/auth/login/",
        {"email": "nobody@example.com", "password": "testpass123"},
        format="json",
    )
    wrong_password = api.post(
        "/api/auth/login/",
        {"email": host.email, "password": "wrongwrong"},
        format="json",
    )
    assert unknown.status_code == wrong_password.status_code == 400
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


def test_me_requires_a_token(api):
    assert api.get("/api/auth/me/").status_code == 401


def test_an_expired_or_bogus_token_is_a_401(api):
    """401 is what drives the client's refresh-then-retry interceptor."""
    api.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
    assert api.get("/api/auth/me/").status_code == 401


def test_refresh_issues_a_working_access_token(api, host):
    tokens = api.post(
        "/api/auth/login/",
        {"email": host.email, "password": "testpass123"},
        format="json",
    ).json()["tokens"]

    refreshed = api.post("/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert refreshed.status_code == 200

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed.json()['access']}")
    assert api.get("/api/auth/me/").status_code == 200


def test_logout_revokes_the_refresh_token(api, host):
    """Signing out must actually end the session, not just forget it locally."""
    tokens = api.post(
        "/api/auth/login/",
        {"email": host.email, "password": "testpass123"},
        format="json",
    ).json()["tokens"]

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert api.post("/api/auth/logout/").status_code == 204
    assert BlacklistedToken.objects.filter(token__user=host).exists()

    api.credentials()
    replayed = api.post("/api/auth/refresh/", {"refresh": tokens["refresh"]}, format="json")
    assert replayed.status_code == 401


def test_profile_updates_are_limited_to_safe_fields(auth, host):
    client = auth(host)
    response = client.patch(
        "/api/auth/me/",
        {"displayName": "Mike", "xp": 999_999, "role": "host"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["displayName"] == "Mike"

    host.refresh_from_db()
    assert host.xp == 0  # `xp` is earned, never asserted by the client


def test_level_is_derived_from_xp_not_set_by_the_client(auth, host):
    host.xp = 1_600
    host.save(update_fields=["xp"])
    assert auth(host).get("/api/auth/me/").json()["level"] == "kingdom_worker"
