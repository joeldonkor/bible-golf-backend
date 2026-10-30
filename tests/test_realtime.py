"""
Two clients, one table, one socket each.

This is the piece the mobile app could not do on its own: a move made by one
phone showing up on the other without either of them asking. Every test here
drives the real ASGI application, so the JWT handshake, the origin check, the
consumer and the channel-layer fan-out are all exercised as deployed.
"""

import pytest
from channels.db import database_sync_to_async
from channels.testing.websocket import WebsocketCommunicator
from rest_framework_simplejwt.tokens import RefreshToken

from config.asgi import application

# `transaction=True` because the consumer reads the database from a worker
# thread, which cannot see rows held inside an unfinished test transaction.
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# Django refuses synchronous database access from a running event loop, so every
# helper below that touches the ORM -- the REST client included -- hops onto a
# worker thread first.


@database_sync_to_async
def access_token(user) -> str:
    return str(RefreshToken.for_user(user).access_token)


@database_sync_to_async
def make_user_async(make_user, **kwargs):
    return make_user(**kwargs)


@database_sync_to_async
def get_json(client, url) -> dict:
    return client.get(url).json()


@database_sync_to_async
def post(client, url, data=None):
    return client.post(url, data or {}, format="json")


async def connect(user, session_id) -> WebsocketCommunicator:
    communicator = WebsocketCommunicator(
        application,
        f"/ws/sessions/{session_id}/?token={await access_token(user)}",
    )
    connected, _ = await communicator.connect()
    assert connected, "websocket handshake was rejected"
    return communicator


async def drain(communicator, *, limit=10) -> list[dict]:
    """Every frame currently queued, without blocking once they run out."""
    frames = []
    for _ in range(limit):
        if await communicator.receive_nothing(timeout=0.2):
            break
        frames.append(await communicator.receive_json_from())
    return frames


async def active_user_id(client, session_id) -> str:
    state = await get_json(client, f"/api/sessions/{session_id}/state/")
    return next(p["userId"] for p in state["players"] if p["id"] == state["activePlayerId"])


# --------------------------------------------------------------------------- #
# Handshake
# --------------------------------------------------------------------------- #


async def test_a_socket_without_a_token_is_refused(table):
    session_id, _, _ = table
    communicator = WebsocketCommunicator(application, f"/ws/sessions/{session_id}/")
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4401
    await communicator.disconnect()


async def test_a_token_for_someone_who_is_not_seated_is_refused(table, make_user):
    session_id, _, _ = table
    stranger = await make_user_async(make_user, email="nosy@example.com", display_name="Nosy")
    communicator = WebsocketCommunicator(
        application, f"/ws/sessions/{session_id}/?token={await access_token(stranger)}"
    )
    connected, code = await communicator.connect()
    assert not connected
    assert code == 4403
    await communicator.disconnect()


async def test_connecting_pushes_the_current_state(table, host):
    session_id, _, _ = table
    communicator = await connect(host, session_id)

    frame = await communicator.receive_json_from(timeout=2)
    assert frame["type"] == "state"
    assert frame["state"]["sessionId"] == str(session_id)
    assert frame["session"]["code"]
    assert frame["version"] >= 1

    await communicator.disconnect()


async def test_the_state_frame_matches_the_rest_bodies(table, host):
    """A client can feed a frame straight into the caches its REST calls fill."""
    session_id, host_client, _ = table
    communicator = await connect(host, session_id)
    frame = await communicator.receive_json_from(timeout=2)

    rest_state = await get_json(host_client, f"/api/sessions/{session_id}/state/")
    rest_session = await get_json(host_client, f"/api/sessions/{session_id}/")

    assert set(frame["state"]) == set(rest_state)
    assert frame["state"]["activePlayerId"] == rest_state["activePlayerId"]
    assert set(frame["session"]) == set(rest_session)
    assert frame["session"]["hostId"] == rest_session["hostId"]

    await communicator.disconnect()


async def test_ping_gets_a_pong(table, host):
    session_id, _, _ = table
    communicator = await connect(host, session_id)
    await drain(communicator)

    await communicator.send_json_to({"action": "ping"})
    assert (await communicator.receive_json_from(timeout=2))["type"] == "pong"

    await communicator.disconnect()


# --------------------------------------------------------------------------- #
# Two clients
# --------------------------------------------------------------------------- #


async def test_presence_reaches_the_other_client(table, host, guest):
    session_id, _, _ = table
    host_socket = await connect(host, session_id)
    await drain(host_socket)

    guest_socket = await connect(guest, session_id)

    frames = await drain(host_socket)
    assert frames, "the host was never told the guest arrived"
    players = frames[-1]["state"]["players"]
    assert any(p["userId"] == str(guest.id) and p["isConnected"] for p in players)

    await guest_socket.disconnect()
    await host_socket.disconnect()


async def test_a_swing_over_the_socket_reaches_the_other_player(table, host, guest):
    """The whole point: one phone acts, the other sees it with no polling."""
    session_id, host_client, _ = table
    host_socket = await connect(host, session_id)
    guest_socket = await connect(guest, session_id)
    await drain(host_socket)
    await drain(guest_socket)

    mover = (
        host_socket
        if await active_user_id(host_client, session_id) == str(host.id)
        else guest_socket
    )
    watcher = guest_socket if mover is host_socket else host_socket

    await mover.send_json_to({"action": "roll"})

    frames = await drain(watcher)
    assert frames, "the watching player never saw the swing"
    latest = frames[-1]
    assert latest["state"]["lastRoll"] is not None
    assert 1 <= latest["state"]["lastRoll"] <= 6
    assert latest["state"]["pendingCard"] is not None

    await host_socket.disconnect()
    await guest_socket.disconnect()


async def test_a_rest_action_is_pushed_to_open_sockets(table, host, guest):
    """HTTP and websocket are the same pipe; an HTTP move still broadcasts."""
    session_id, host_client, guest_client = table
    watcher = await connect(guest, session_id)
    await drain(watcher)

    mover_client = (
        host_client
        if await active_user_id(host_client, session_id) == str(host.id)
        else guest_client
    )
    await post(mover_client, f"/api/sessions/{session_id}/roll/")

    frames = await drain(watcher)
    assert frames
    assert frames[-1]["state"]["lastRoll"] is not None

    await watcher.disconnect()


async def test_playing_out_of_turn_errors_only_that_socket(table, host, guest):
    session_id, host_client, _ = table
    host_socket = await connect(host, session_id)
    guest_socket = await connect(guest, session_id)
    await drain(host_socket)
    await drain(guest_socket)

    waiting = (
        guest_socket
        if await active_user_id(host_client, session_id) == str(host.id)
        else host_socket
    )
    other = host_socket if waiting is guest_socket else guest_socket

    await waiting.send_json_to({"action": "roll"})

    error = await waiting.receive_json_from(timeout=2)
    assert error["type"] == "error"
    assert "turn" in error["detail"].lower()
    # Nothing changed, so nobody else is bothered.
    assert await other.receive_nothing(timeout=0.3)

    await host_socket.disconnect()
    await guest_socket.disconnect()


async def test_versions_only_move_forward(table, host, guest):
    session_id, host_client, _ = table
    host_socket = await connect(host, session_id)
    guest_socket = await connect(guest, session_id)
    await drain(host_socket)
    await drain(guest_socket)

    mover = (
        host_socket
        if await active_user_id(host_client, session_id) == str(host.id)
        else guest_socket
    )

    await mover.send_json_to({"action": "roll"})
    first = await drain(mover)
    await mover.send_json_to({"action": "resolveCard", "choiceIndex": None})
    second = await drain(mover, limit=20)

    versions = [f["version"] for f in first + second if f["type"] == "state"]
    assert versions == sorted(versions)
    assert versions[-1] > versions[0]

    await host_socket.disconnect()
    await guest_socket.disconnect()


async def test_sync_resends_state_on_demand(table, host):
    session_id, _, _ = table
    communicator = await connect(host, session_id)
    await drain(communicator)

    await communicator.send_json_to({"action": "sync"})
    frame = await communicator.receive_json_from(timeout=2)
    assert frame["type"] == "state"

    await communicator.disconnect()


async def test_an_unknown_action_is_reported_not_ignored(table, host):
    session_id, _, _ = table
    communicator = await connect(host, session_id)
    await drain(communicator)

    await communicator.send_json_to({"action": "teleport"})
    frame = await communicator.receive_json_from(timeout=2)
    assert frame["type"] == "error"
    assert frame["code"] == "unknown_action"

    await communicator.disconnect()


async def test_disconnecting_marks_the_player_offline(table, host, guest):
    session_id, _, _ = table
    host_socket = await connect(host, session_id)
    guest_socket = await connect(guest, session_id)
    await drain(host_socket)
    await drain(guest_socket)

    await guest_socket.disconnect()

    frames = await drain(host_socket)
    assert frames, "the host was never told the guest left"
    players = frames[-1]["state"]["players"]
    assert any(p["userId"] == str(guest.id) and not p["isConnected"] for p in players)

    await host_socket.disconnect()
