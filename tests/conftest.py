"""Shared fixtures."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.decks.models import Card, Deck
from apps.games.models import GameSession

User = get_user_model()


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(email="player@example.com", display_name="Player", **extra):
        return User.objects.create_user(
            email=email, password="testpass123", display_name=display_name, **extra
        )

    return _make


@pytest.fixture
def host(make_user):
    return make_user(email="host@example.com", display_name="Michael")


@pytest.fixture
def guest(make_user):
    return make_user(email="guest@example.com", display_name="Sarah")


@pytest.fixture
def auth(api):
    """Authenticate `api` as a user and hand the client back."""

    def _auth(user, client=None):
        client = client or APIClient()
        client.force_authenticate(user=user)
        return client

    return _auth


@pytest.fixture
def deck(db) -> Deck:
    deck = Deck.objects.create(
        name="Parables", description="Stories Jesus told.", is_custom=False
    )
    Card.objects.create(
        deck=deck,
        type=Card.TYPE_QUESTION,
        rarity="common",
        title="Complete the Verse",
        prompt="In the beginning God created the ______ and the earth.",
        reference="Genesis 1:1",
        options=["Firmament", "Heavens", "Stars", "Oceans"],
        correct_option_index=1,
        effect={"points": 15},
    )
    Card.objects.create(
        deck=deck,
        type=Card.TYPE_SCRIPTURE,
        rarity="legendary",
        title="The Lost Sheep",
        prompt="Rejoice with me; I have found my lost sheep.",
        reference="Luke 15:6",
        effect={"move": 1, "points": 10},
    )
    return deck


@pytest.fixture
def table(auth, host, guest, deck):
    """
    A started two-player round, as the two clients would set it up.

    Returns `(session_id, host_client, guest_client)`.
    """
    host_client = auth(host)
    guest_client = auth(guest)

    created = host_client.post(
        "/api/sessions/",
        {"name": "Sunday Night", "deckId": str(deck.id), "maxPlayers": 4},
        format="json",
    )
    assert created.status_code == 201, created.data
    session_id = created.data["id"]

    joined = guest_client.post(
        "/api/sessions/join/", {"code": created.data["code"]}, format="json"
    )
    assert joined.status_code == 200, joined.data

    started = host_client.post(f"/api/sessions/{session_id}/start/", format="json")
    assert started.status_code == 200, started.data

    # Bypass the growth-ladder phase so board tests don't have to roll sixes.
    session = GameSession.objects.get(pk=session_id)
    session.stage = GameSession.STAGE_MAIN_JOURNEY
    session.save(update_fields=["stage", "updated_at"])
    session.players.update(has_entered_main_board=True, ladder_position=7)

    return session_id, host_client, guest_client
