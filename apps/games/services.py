"""
The one place a game mutation happens.

REST handlers and the websocket consumer both call in here, so a swing taken
over a socket and a swing taken over HTTP follow byte-for-byte the same path:
lock the session row, apply the rule, log the event, broadcast the new state.
Duplicating that in two transports is how the two drift apart.
"""

import logging

from django.db import transaction

from apps.common.db import locked
from apps.common.exceptions import ConflictError

from . import engine
from .broadcast import broadcast_state, reload_for_broadcast
from .models import GameSession, Player

logger = logging.getLogger(__name__)


def visible_sessions(user):
    """Sessions the user is seated at."""
    return GameSession.objects.filter(players__user=user).distinct()


def active_session_for(user) -> GameSession | None:
    """Drives the Home screen's "Continue" card."""
    return (
        GameSession.objects.with_related()
        .filter(players__user=user)
        .exclude(status=GameSession.STATUS_COMPLETED)
        .order_by("-updated_at")
        .first()
    )


def _finish(session_id) -> GameSession:
    """Reload with relations and publish the result once the write lands."""
    session = reload_for_broadcast(session_id)
    broadcast_state(session)
    return session


# --------------------------------------------------------------------------- #
# Lobby
# --------------------------------------------------------------------------- #


def create_session(*, user, name: str, deck, max_players: int) -> GameSession:
    with transaction.atomic():
        session = engine.create_session(
            user=user, name=name, deck=deck, max_players=max_players
        )
        # Creating a table is what makes someone a host.
        if user.role != user.ROLE_HOST:
            user.role = user.ROLE_HOST
            user.save(update_fields=["role"])
    return _finish(session.id)


def join_session(*, user, code: str) -> GameSession:
    session_id = GameSession.objects.filter(code=code).values_list("id", flat=True).first()
    if session_id is None:
        raise ConflictError("No table with that code. Double-check it with the host.")

    with locked(GameSession.objects.all(), session_id) as session:
        engine.join_session(session=session, user=user)
    return _finish(session_id)


def start_session(*, user, session_id) -> GameSession:
    with locked(GameSession.objects.all(), session_id) as session:
        engine.start_session(session=session, user=user)
    return _finish(session_id)


def leave_session(*, user, session_id) -> None:
    with locked(GameSession.objects.all(), session_id) as session:
        engine.leave_session(session=session, user=user)
    _finish(session_id)


# --------------------------------------------------------------------------- #
# Turns
# --------------------------------------------------------------------------- #


def take_swing(*, user, session_id) -> GameSession:
    with locked(GameSession.objects.all(), session_id) as session:
        outcome = engine.take_swing(session=session, user=user)
        completed = session.status == GameSession.STATUS_COMPLETED
    logger.info(
        "swing_taken",
        extra={"session_id": str(session_id), "roll": outcome.payload["value"]},
    )
    if completed:
        _award_badges(session_id)
    return _finish(session_id)


def resolve_card(*, user, session_id, choice_index: int | None) -> GameSession:
    with locked(GameSession.objects.all(), session_id) as session:
        engine.resolve_card(session=session, user=user, choice_index=choice_index)
        completed = session.status == GameSession.STATUS_COMPLETED
    if completed:
        _award_badges(session_id)
    return _finish(session_id)


def _award_badges(session_id) -> None:
    """
    Check everyone's achievements once the round ends.

    Imported lazily: `leaderboard` reads `games` models, so a module-level
    import here would close the cycle. Failures are swallowed -- a missed badge
    is a cosmetic loss and must never roll back a finished game.
    """
    from apps.leaderboard.services import evaluate_badges

    seats = Player.objects.filter(session_id=session_id).select_related("user")
    for seat in seats:
        try:
            evaluate_badges(seat.user)
        except Exception:
            logger.exception("badge_evaluation_failed", extra={"user_id": str(seat.user_id)})


def skip_turn(*, user, session_id) -> GameSession:
    with locked(GameSession.objects.all(), session_id) as session:
        engine.skip_stalled_turn(session=session, user=user)
    return _finish(session_id)


# --------------------------------------------------------------------------- #
# Presence
# --------------------------------------------------------------------------- #


def set_presence(*, user_id, session_id, delta: int) -> GameSession | None:
    """
    Track how many live sockets a player holds.

    A phone that backgrounds and resumes can briefly hold two connections, so a
    boolean would flicker "offline" the moment the old one closed. Counting
    connections and clamping at zero keeps the lobby's presence dot honest.
    """
    from django.db.models import F, Value
    from django.db.models.functions import Greatest
    from django.utils import timezone

    updated = Player.objects.filter(session_id=session_id, user_id=user_id).update(
        connection_count=Greatest(F("connection_count") + delta, Value(0)),
        last_seen_at=timezone.now(),
    )
    if not updated:
        return None
    return reload_for_broadcast(session_id)
