"""
Fan-out of authoritative game state to every socket at a table.

The frame is built *once*, by whoever performed the mutation, and shipped
through the channel layer fully rendered. Consumers then do no database work at
all on the fan-out path, so adding players to a table costs a Redis publish and
a socket write each -- not another round of queries.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from djangorestframework_camel_case.util import camelize

from .models import GameSession
from .serializers import GameStateSerializer, SessionSerializer

logger = logging.getLogger(__name__)

# Frame types the client can receive.
FRAME_STATE = "state"
FRAME_ERROR = "error"
FRAME_PONG = "pong"


def group_name(session_id) -> str:
    return f"session.{session_id}"


def build_state_frame(session: GameSession, *, event: dict | None = None) -> dict:
    """
    Render one broadcast frame.

    `state` is exactly the body `GET /sessions/{id}/state/` returns and `session`
    exactly what `GET /sessions/{id}/` returns, so a websocket client can feed
    both straight into the same React Query caches the REST calls populate.

    Camelising happens here because websocket frames never pass through DRF's
    renderer -- without it, sockets would speak snake_case while the REST API
    spoke camelCase, and the client would need two mappings for one contract.
    """
    return {
        "type": FRAME_STATE,
        "version": session.version,
        "state": camelize(GameStateSerializer(session).data),
        "session": camelize(SessionSerializer(session).data),
        "event": camelize(event) if event else None,
    }


def _send(session_id, frame: dict) -> None:
    layer = get_channel_layer()
    if layer is None:  # pragma: no cover - only when misconfigured
        logger.warning("no_channel_layer", extra={"session_id": str(session_id)})
        return
    try:
        async_to_sync(layer.group_send)(
            group_name(session_id), {"type": "session.frame", "frame": frame}
        )
    except Exception:
        # A realtime hiccup must never fail the HTTP request that caused it --
        # the client polls as a fallback and will converge either way.
        logger.exception("broadcast_failed", extra={"session_id": str(session_id)})


def broadcast_state(session: GameSession, *, event: dict | None = None) -> None:
    """
    Publish the session's current state to its group after the transaction commits.

    Broadcasting mid-transaction would let a listener read a state that a
    rollback then erases -- `on_commit` makes "sent" mean "durable".
    """
    frame = build_state_frame(session, event=event)
    session_id = session.id
    transaction.on_commit(lambda: _send(session_id, frame))


def reload_for_broadcast(session_id) -> GameSession:
    """Re-read a session with every relation the frame needs, in one trip."""
    return GameSession.objects.with_related().get(pk=session_id)
