"""
Two taps at the same instant.

A turn is a read-modify-write on the session, so without the row lock in
`apps.common.db.locked` both requests read the same board and one write is
silently lost -- the classic way a multiplayer game ends up with a player who
moved twice on one roll.

Real row locking needs `SELECT ... FOR UPDATE`, which SQLite doesn't have, so
these run only against PostgreSQL. SQLite's own writer lock serialises the
transaction, which is why the rest of the suite is still correct there.
"""

import threading

import pytest
from django.db import connection, connections

from apps.games.models import Player

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.slow,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="row-level locking requires PostgreSQL",
    ),
]


def test_simultaneous_swings_only_move_the_player_once(table, host, guest):
    session_id, host_client, guest_client = table
    state = host_client.get(f"/api/sessions/{session_id}/state/").json()
    mover = Player.objects.select_related("user").get(pk=state["activePlayerId"])
    client = host_client if mover.user_id == host.id else guest_client

    results: list[int] = []
    barrier = threading.Barrier(2)

    def swing():
        barrier.wait()
        try:
            response = client.post(f"/api/sessions/{session_id}/roll/", format="json")
            results.append(response.status_code)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=swing) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [200, 422], results

    mover.refresh_from_db()
    assert mover.score == 1  # exactly one stroke, not two
    assert mover.position <= 6
