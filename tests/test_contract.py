"""
The contract with the mobile client.

Every key set below is copied from `src/types/*.ts`. If a rename here doesn't
also happen there, the app silently renders `undefined` -- so these assertions
are deliberately exact rather than "contains".
"""

import pytest

pytestmark = pytest.mark.django_db


def body(response):
    """
    The *rendered* body.

    `response.data` is the pre-render structure and is still snake_case --
    camelising happens in the renderer, which is exactly what these tests are
    checking, so every assertion here goes through JSON.
    """
    return response.json()


USER_KEYS = {
    "id",
    "email",
    "displayName",
    "avatarUrl",
    "role",
    "level",
    "xp",
    "createdAt",
}

PLAYER_KEYS = {
    "id",
    "userId",
    "displayName",
    "avatarUrl",
    "level",
    "position",
    "score",
    "isHost",
    "isConnected",
    "hasEnteredMainBoard",
}

SESSION_KEYS = {
    "id",
    "code",
    "name",
    "hostId",
    "status",
    "stage",
    "players",
    "deckId",
    "maxPlayers",
    "createdAt",
}

# `version` is an addition the websocket client uses to discard stale frames;
# the client's `GameState` type simply ignores it.
GAME_STATE_KEYS = {
    "sessionId",
    "status",
    "stage",
    "activePlayerId",
    "turnNumber",
    "lastRoll",
    "pendingCard",
    "players",
    "version",
}

CARD_KEYS = {
    "id",
    "deckId",
    "type",
    "rarity",
    "title",
    "prompt",
    "reference",
    "options",
    "correctOptionIndex",
    "artUrl",
    "effect",
}

DECK_KEYS = {
    "id",
    "name",
    "description",
    "coverUrl",
    "cardCount",
    "isCustom",
    "ownerId",
    "updatedAt",
}

PAGINATED_KEYS = {"count", "next", "previous", "results"}


def test_auth_session_shape(api, host):
    response = api.post(
        "/api/auth/login/",
        {"email": host.email, "password": "testpass123"},
        format="json",
    )
    assert response.status_code == 200
    assert set(body(response)) == {"user", "tokens"}
    assert set(body(response)["user"]) == USER_KEYS
    assert set(body(response)["tokens"]) == {"access", "refresh"}


def test_register_returns_session(api):
    response = api.post(
        "/api/auth/register/",
        {
            "email": "new@example.com",
            "password": "testpass123",
            "displayName": "Ruth",
        },
        format="json",
    )
    assert response.status_code == 201, body(response)
    assert set(body(response)["user"]) == USER_KEYS
    assert body(response)["user"]["displayName"] == "Ruth"
    assert body(response)["user"]["level"] == "bible_student"


def test_refresh_returns_access_only(api, host):
    login = api.post(
        "/api/auth/login/",
        {"email": host.email, "password": "testpass123"},
        format="json",
    )
    refresh = body(login)["tokens"]["refresh"]

    response = api.post("/api/auth/refresh/", {"refresh": refresh}, format="json")
    assert response.status_code == 200
    assert set(body(response)) == {"access"}


def test_deck_list_shape(auth, host, deck):
    response = auth(host).get("/api/decks/")
    assert response.status_code == 200
    assert set(body(response)) == PAGINATED_KEYS
    assert set(body(response)["results"][0]) == DECK_KEYS
    assert body(response)["results"][0]["cardCount"] == 2


def test_deck_cards_shape(auth, host, deck):
    response = auth(host).get(f"/api/decks/{deck.id}/cards/")
    assert response.status_code == 200
    assert set(body(response)) == PAGINATED_KEYS
    card = body(response)["results"][0]
    assert set(card) == CARD_KEYS
    # Effect keys reach the client camelised, matching `CardEffect`.
    assert set(card["effect"]) <= {"move", "points", "skipTurn"}


def test_session_and_state_shape(table):
    session_id, host_client, _ = table

    session = host_client.get(f"/api/sessions/{session_id}/")
    assert set(body(session)) == SESSION_KEYS
    assert set(body(session)["players"][0]) == PLAYER_KEYS

    state = host_client.get(f"/api/sessions/{session_id}/state/")
    assert set(body(state)) == GAME_STATE_KEYS
    assert set(body(state)["players"][0]) == PLAYER_KEYS


def test_host_id_is_a_player_id_not_a_user_id(table):
    """`LobbyScreen` resolves the host via `players.find(p => p.id === hostId)`."""
    session_id, host_client, _ = table
    session = host_client.get(f"/api/sessions/{session_id}/").json()

    host_player = next(p for p in session["players"] if p["isHost"])
    assert session["hostId"] == host_player["id"]
    assert session["hostId"] != host_player["userId"]


def test_active_session_is_null_when_none(auth, guest):
    response = auth(guest).get("/api/sessions/active/")
    assert response.status_code == 200
    assert body(response) is None


def test_active_session_returns_the_live_table(table):
    session_id, host_client, _ = table
    response = host_client.get("/api/sessions/active/")
    assert response.status_code == 200
    assert body(response)["id"] == session_id


def test_leaderboard_shape(auth, host):
    response = auth(host).get("/api/leaderboard/", {"scope": "global"})
    assert response.status_code == 200
    assert set(body(response)) == PAGINATED_KEYS
    assert set(body(response)["results"][0]) == {
        "rank",
        "userId",
        "displayName",
        "avatarUrl",
        "points",
        "level",
        "title",
    }


def test_badges_shape(auth, host):
    from apps.leaderboard.models import Badge

    Badge.objects.create(
        code="word-watcher",
        name="Word Watcher",
        description="Resolve 7 cards.",
        icon_name="book",
        criteria={"type": Badge.CRITERIA_CARDS, "value": 7},
    )
    response = auth(host).get("/api/leaderboard/badges/")
    assert response.status_code == 200
    assert set(body(response)) == PAGINATED_KEYS
    assert set(body(response)["results"][0]) == {
        "id",
        "name",
        "description",
        "iconName",
        "earned",
    }


def test_errors_carry_a_string_detail_and_field_errors(api):
    """`src/api/errors.ts` reads `detail`, then any list-of-strings field."""
    response = api.post(
        "/api/auth/register/",
        {"email": "not-an-email", "password": "x", "displayName": "A"},
        format="json",
    )
    assert response.status_code == 400
    assert isinstance(body(response)["detail"], str)
    assert isinstance(body(response)["email"], list)
    # Field names arrive camelised so react-hook-form can map them by name.
    assert "displayName" in body(response)
