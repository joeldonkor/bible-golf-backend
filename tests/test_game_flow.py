"""
Two real clients playing a round.

These are the rules the client can no longer enforce for itself once the mock
engine is gone: whose turn it is, what a swing costs, and what an answer is
worth.
"""

import pytest

from apps.decks.models import Card
from apps.games.models import GameEvent, GameSession, Player

pytestmark = pytest.mark.django_db


def state_of(client, session_id) -> dict:
    return client.get(f"/api/sessions/{session_id}/state/").json()


def active_client(session_id, host_client, guest_client, host, guest):
    """Whichever client's user currently holds the turn."""
    state = state_of(host_client, session_id)
    active = next(p for p in state["players"] if p["id"] == state["activePlayerId"])
    return host_client if active["userId"] == str(host.id) else guest_client


# --------------------------------------------------------------------------- #
# Lobby
# --------------------------------------------------------------------------- #


def test_create_seats_the_host_first(auth, host, deck):
    response = auth(host).post(
        "/api/sessions/",
        {"name": "Sunday Night", "deckId": str(deck.id)},
        format="json",
    )
    assert response.status_code == 201
    session = response.json()
    assert session["status"] == "lobby"
    assert session["stage"] == "growth_ladder"
    assert len(session["players"]) == 1
    assert session["players"][0]["isHost"] is True
    assert len(session["code"]) == 6


def test_join_by_code_is_idempotent(auth, host, guest, deck):
    host_client, guest_client = auth(host), auth(guest)
    code = host_client.post(
        "/api/sessions/", {"name": "Table", "deckId": str(deck.id)}, format="json"
    ).json()["code"]

    first = guest_client.post("/api/sessions/join/", {"code": code}, format="json")
    second = guest_client.post("/api/sessions/join/", {"code": code}, format="json")

    assert first.status_code == second.status_code == 200
    assert len(second.json()["players"]) == 2


def test_join_is_case_insensitive(auth, host, guest, deck):
    host_client, guest_client = auth(host), auth(guest)
    code = host_client.post(
        "/api/sessions/", {"name": "Table", "deckId": str(deck.id)}, format="json"
    ).json()["code"]

    response = guest_client.post("/api/sessions/join/", {"code": code.lower()}, format="json")
    assert response.status_code == 200


def test_join_rejects_a_full_table(auth, host, guest, make_user, deck):
    host_client = auth(host)
    code = host_client.post(
        "/api/sessions/",
        {"name": "Table", "deckId": str(deck.id), "maxPlayers": 2},
        format="json",
    ).json()["code"]

    assert (
        auth(guest).post("/api/sessions/join/", {"code": code}, format="json").status_code
        == 200
    )
    third = make_user(email="third@example.com", display_name="David")
    response = auth(third).post("/api/sessions/join/", {"code": code}, format="json")
    assert response.status_code == 409
    assert "full" in response.json()["detail"].lower()


def test_join_rejects_an_unknown_code(auth, guest):
    response = auth(guest).post("/api/sessions/join/", {"code": "ZZZZZZ"}, format="json")
    assert response.status_code == 409


def test_only_the_host_can_start(auth, host, guest, deck):
    host_client, guest_client = auth(host), auth(guest)
    created = host_client.post(
        "/api/sessions/", {"name": "Table", "deckId": str(deck.id)}, format="json"
    ).json()
    guest_client.post("/api/sessions/join/", {"code": created["code"]}, format="json")

    response = guest_client.post(f"/api/sessions/{created['id']}/start/", format="json")
    assert response.status_code == 422
    assert "host" in response.json()["detail"].lower()


def test_start_moves_everyone_onto_the_main_board(table):
    session_id, host_client, _ = table
    state = state_of(host_client, session_id)
    assert state["status"] == "active"
    assert state["stage"] == "main_journey"
    assert all(p["hasEnteredMainBoard"] for p in state["players"])
    assert state["activePlayerId"] is not None


def test_a_stranger_cannot_see_the_table(table, auth, make_user):
    session_id, _, _ = table
    stranger = make_user(email="nosy@example.com", display_name="Nosy")
    assert auth(stranger).get(f"/api/sessions/{session_id}/").status_code == 404
    assert auth(stranger).get(f"/api/sessions/{session_id}/state/").status_code == 404


# --------------------------------------------------------------------------- #
# Turns
# --------------------------------------------------------------------------- #


def test_only_the_active_player_may_swing(table, host, guest):
    session_id, host_client, guest_client = table
    waiting = (
        guest_client
        if active_client(session_id, host_client, guest_client, host, guest) is host_client
        else host_client
    )
    response = waiting.post(f"/api/sessions/{session_id}/roll/", format="json")
    assert response.status_code == 422
    assert "turn" in response.json()["detail"].lower()


def test_a_swing_costs_a_stroke_and_moves_the_player(table, host, guest):
    session_id, host_client, guest_client = table
    client = active_client(session_id, host_client, guest_client, host, guest)

    before = state_of(host_client, session_id)
    mover_id = before["activePlayerId"]

    after = client.post(f"/api/sessions/{session_id}/roll/", format="json").json()
    mover = next(p for p in after["players"] if p["id"] == mover_id)

    assert 1 <= after["lastRoll"] <= 6
    assert mover["position"] == after["lastRoll"]
    assert mover["score"] == 1


def test_a_swing_draws_a_card_that_must_be_resolved_first(table, host, guest):
    session_id, host_client, guest_client = table
    client = active_client(session_id, host_client, guest_client, host, guest)

    after = client.post(f"/api/sessions/{session_id}/roll/", format="json").json()
    assert after["pendingCard"] is not None

    again = client.post(f"/api/sessions/{session_id}/roll/", format="json")
    assert again.status_code == 422
    assert "card" in again.json()["detail"].lower()


def test_resolving_passes_the_turn_to_the_other_player(table, host, guest):
    session_id, host_client, guest_client = table
    client = active_client(session_id, host_client, guest_client, host, guest)

    rolled = client.post(f"/api/sessions/{session_id}/roll/", format="json").json()
    first_player = rolled["activePlayerId"]

    resolved = client.post(
        f"/api/sessions/{session_id}/resolve-card/", {}, format="json"
    ).json()

    assert resolved["pendingCard"] is None
    assert resolved["activePlayerId"] != first_player
    assert resolved["turnNumber"] > rolled["turnNumber"]


def test_a_right_answer_is_a_birdie_and_a_wrong_one_a_bogey(table, host, guest, deck):
    """A correct answer takes a stroke back; a wrong one adds another."""
    session_id, host_client, guest_client = table
    session = GameSession.objects.get(pk=session_id)
    question = deck.cards.get(type=Card.TYPE_QUESTION)

    for choice, expected_delta in ((question.correct_option_index, -1), (0, 1)):
        client = active_client(session_id, host_client, guest_client, host, guest)
        client.post(f"/api/sessions/{session_id}/roll/", format="json")

        # Force the drawn card so the assertion doesn't depend on the shuffle.
        session.refresh_from_db()
        session.pending_card = question
        session.save(update_fields=["pending_card"])

        before = state_of(host_client, session_id)
        mover_id = before["activePlayerId"]
        score_before = next(p for p in before["players"] if p["id"] == mover_id)["score"]

        after = client.post(
            f"/api/sessions/{session_id}/resolve-card/",
            {"choiceIndex": choice},
            format="json",
        ).json()
        score_after = next(p for p in after["players"] if p["id"] == mover_id)["score"]
        assert score_after - score_before == expected_delta


def test_declining_to_answer_scores_par(table, host, guest, deck):
    """ "Use Life" sends no choice, so the question costs nothing extra."""
    session_id, host_client, guest_client = table
    client = active_client(session_id, host_client, guest_client, host, guest)
    client.post(f"/api/sessions/{session_id}/roll/", format="json")

    session = GameSession.objects.get(pk=session_id)
    session.pending_card = deck.cards.get(type=Card.TYPE_QUESTION)
    session.save(update_fields=["pending_card"])

    before = state_of(host_client, session_id)
    mover_id = before["activePlayerId"]
    score_before = next(p for p in before["players"] if p["id"] == mover_id)["score"]

    after = client.post(f"/api/sessions/{session_id}/resolve-card/", {}, format="json").json()
    score_after = next(p for p in after["players"] if p["id"] == mover_id)["score"]
    assert score_after == score_before


def test_a_correct_answer_awards_points_and_xp(table, host, guest, deck):
    session_id, host_client, guest_client = table
    question = deck.cards.get(type=Card.TYPE_QUESTION)

    client = active_client(session_id, host_client, guest_client, host, guest)
    client.post(f"/api/sessions/{session_id}/roll/", format="json")

    session = GameSession.objects.get(pk=session_id)
    session.pending_card = question
    session.save(update_fields=["pending_card"])
    mover = Player.objects.get(pk=state_of(host_client, session_id)["activePlayerId"])
    xp_before = mover.user.xp

    client.post(
        f"/api/sessions/{session_id}/resolve-card/",
        {"choiceIndex": question.correct_option_index},
        format="json",
    )

    mover.user.refresh_from_db()
    assert mover.user.xp == xp_before + question.effect["points"]
    assert mover.user.points == question.effect["points"]


def test_a_wrong_answer_earns_nothing(table, host, guest, deck):
    session_id, host_client, guest_client = table
    question = deck.cards.get(type=Card.TYPE_QUESTION)
    wrong = 1 - question.correct_option_index

    client = active_client(session_id, host_client, guest_client, host, guest)
    client.post(f"/api/sessions/{session_id}/roll/", format="json")

    session = GameSession.objects.get(pk=session_id)
    session.pending_card = question
    session.save(update_fields=["pending_card"])
    mover = Player.objects.get(pk=state_of(host_client, session_id)["activePlayerId"])

    client.post(
        f"/api/sessions/{session_id}/resolve-card/",
        {"choiceIndex": wrong},
        format="json",
    )
    mover.user.refresh_from_db()
    assert mover.user.points == 0


def test_reaching_the_last_hole_ends_the_round(table, host, guest, settings):
    session_id, host_client, guest_client = table
    client = active_client(session_id, host_client, guest_client, host, guest)

    # Park the active player one short of the pin so the next swing must finish.
    mover = Player.objects.get(pk=state_of(host_client, session_id)["activePlayerId"])
    mover.position = settings.TOTAL_HOLES - 1
    mover.save(update_fields=["position"])

    after = client.post(f"/api/sessions/{session_id}/roll/", format="json").json()

    assert after["status"] == "completed"
    assert after["activePlayerId"] is None
    assert after["pendingCard"] is None
    winner = next(p for p in after["players"] if p["id"] == str(mover.id))
    assert winner["position"] == settings.TOTAL_HOLES

    # And the table is closed for business.
    assert client.post(f"/api/sessions/{session_id}/roll/", format="json").status_code == 422


def test_a_finished_round_stops_being_the_active_one(table, host, guest, settings):
    session_id, host_client, guest_client = table
    client = active_client(session_id, host_client, guest_client, host, guest)
    mover = Player.objects.get(pk=state_of(host_client, session_id)["activePlayerId"])
    mover.position = settings.TOTAL_HOLES - 1
    mover.save(update_fields=["position"])
    client.post(f"/api/sessions/{session_id}/roll/", format="json")

    assert host_client.get("/api/sessions/active/").json() is None


# --------------------------------------------------------------------------- #
# Leaving
# --------------------------------------------------------------------------- #


def test_the_host_leaving_promotes_the_next_seat(table, host, guest):
    session_id, host_client, guest_client = table

    assert host_client.post(f"/api/sessions/{session_id}/leave/").status_code == 204

    session = guest_client.get(f"/api/sessions/{session_id}/").json()
    assert len(session["players"]) == 1
    assert session["players"][0]["userId"] == str(guest.id)
    assert session["players"][0]["isHost"] is True
    assert session["hostId"] == session["players"][0]["id"]


def test_the_turn_moves_on_when_the_active_player_leaves(table, host, guest):
    session_id, host_client, guest_client = table
    state = state_of(host_client, session_id)
    active = next(p for p in state["players"] if p["id"] == state["activePlayerId"])
    leaving = host_client if active["userId"] == str(host.id) else guest_client
    staying = guest_client if leaving is host_client else host_client

    leaving.post(f"/api/sessions/{session_id}/leave/")

    after = state_of(staying, session_id)
    assert after["activePlayerId"] is not None
    assert after["activePlayerId"] != active["id"]


def test_the_last_player_leaving_closes_the_table(table, host, guest):
    session_id, host_client, guest_client = table
    host_client.post(f"/api/sessions/{session_id}/leave/")
    guest_client.post(f"/api/sessions/{session_id}/leave/")

    assert GameSession.objects.get(pk=session_id).status == "completed"


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #


def test_every_action_is_logged_in_order(table, host, guest):
    session_id, host_client, guest_client = table
    client = active_client(session_id, host_client, guest_client, host, guest)
    client.post(f"/api/sessions/{session_id}/roll/", format="json")
    client.post(f"/api/sessions/{session_id}/resolve-card/", {}, format="json")

    events = list(
        GameEvent.objects.filter(session_id=session_id).values_list("type", flat=True)
    )
    assert events[:2] == [GameEvent.TYPE_CREATED, GameEvent.TYPE_PLAYER_JOINED]
    assert GameEvent.TYPE_ROLLED in events
    assert GameEvent.TYPE_CARD_RESOLVED in events

    sequences = list(
        GameEvent.objects.filter(session_id=session_id).values_list("sequence", flat=True)
    )
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    # The session's version is the sequence of its newest event.
    assert GameSession.objects.get(pk=session_id).version == sequences[-1]


def test_events_endpoint_replays_the_round(table, host, guest):
    session_id, host_client, guest_client = table
    response = host_client.get(f"/api/sessions/{session_id}/events/")
    assert response.status_code == 200
    body = response.json()
    assert {"count", "next", "previous", "results"} == set(body)
    assert body["results"]
