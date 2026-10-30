"""
The authoritative rules of Bible Golf.

This is the server-side twin of the client's `src/services/sessions/gameEngine.ts`,
with one deliberate difference: the client's mock hands every turn back to the
local human and simulates opponents, whereas here the turn genuinely rotates
between real players. The client already gates its "Take Swing" button on
`activePlayerId`, so that difference needs no UI change.

Every function assumes the caller holds a row lock on the session (see
`apps.common.db.locked`) -- these are read-modify-write sequences, and without
the lock two players tapping at the same instant would both read the same board
and one update would vanish.
"""

import logging
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import ConflictError, DomainError
from apps.decks.models import Card, Deck

from .models import GameEvent, GameSession, Player

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Scoring constants -- golf terms, so lower is better.
# --------------------------------------------------------------------------- #

STROKE = 1  # every swing costs a stroke
BIRDIE = -1  # a correct answer takes one back
BOGEY = 1  # a wrong answer costs another


@dataclass(frozen=True)
class TurnOutcome:
    """What a mutation produced, for the event log and the broadcast."""

    session: GameSession
    event_type: str
    payload: dict


def roll_die() -> int:
    """A fair d6 from the CSPRNG -- game outcomes shouldn't be predictable."""
    return secrets.randbelow(settings.DIE_SIDES) + 1


# --------------------------------------------------------------------------- #
# Event log
# --------------------------------------------------------------------------- #


def record_event(
    session: GameSession, event_type: str, payload: dict, actor: Player | None = None
) -> GameEvent:
    """
    Append to the session's log and bump its version.

    The session's `version` *is* the sequence number of its latest event. One
    counter for both means a websocket client that has applied version N knows
    precisely which events it has already seen, and a frame that arrives out of
    order is simply an older number it can drop.

    Callers hold the session row lock, so the read-increment-write is safe.
    """
    session.version += 1
    session.save(update_fields=["version", "updated_at"])
    return GameEvent.objects.create(
        session=session,
        sequence=session.version,
        type=event_type,
        actor=actor,
        payload=payload,
    )


# --------------------------------------------------------------------------- #
# Lobby
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_session(*, user, name: str, deck: Deck, max_players: int = 4) -> GameSession:
    session = GameSession.create_with_code(
        name=name.strip(),
        host=user,
        deck=deck,
        max_players=max_players,
        status=GameSession.STATUS_LOBBY,
        stage=GameSession.STAGE_GROWTH_LADDER,
    )
    host_player = Player.objects.create(session=session, user=user, turn_order=0, is_host=True)
    session.active_player = host_player
    session.save(update_fields=["active_player", "updated_at"])

    record_event(
        session,
        GameEvent.TYPE_CREATED,
        {"code": session.code, "name": session.name},
        actor=host_player,
    )
    logger.info(
        "session_created",
        extra={"session_id": str(session.id), "code": session.code},
    )
    return session


def join_session(*, session: GameSession, user) -> Player:
    """
    Seat a user at an existing table. Idempotent for someone already seated.

    Assumes `session` was fetched under a row lock, so the seat count and the
    seat number it hands out can't be raced by a simultaneous join.
    """
    existing = session.players.filter(user=user).first()
    if existing is not None:
        return existing

    if session.status == GameSession.STATUS_COMPLETED:
        raise ConflictError("That round has already finished.")
    if session.status == GameSession.STATUS_ACTIVE:
        raise ConflictError("That round is already under way.")

    seats_taken = session.players.count()
    if seats_taken >= session.max_players:
        raise ConflictError("That table is full.")

    player = Player.objects.create(
        session=session, user=user, turn_order=seats_taken, is_host=False
    )
    record_event(
        session,
        GameEvent.TYPE_PLAYER_JOINED,
        {"player_id": str(player.id), "display_name": user.display_name},
        actor=player,
    )
    return player


def start_session(*, session: GameSession, user) -> GameSession:
    if session.host_id != user.id:
        raise DomainError("Only the host can start the round.")
    if session.status == GameSession.STATUS_ACTIVE:
        # Two taps on "Start Game" shouldn't reset a round in progress.
        return session
    if session.status == GameSession.STATUS_COMPLETED:
        raise ConflictError("That round has already finished.")

    players = list(session.players.order_by("turn_order"))
    if not players:
        raise DomainError("A round needs at least one player.")

    session.status = GameSession.STATUS_ACTIVE
    session.stage = GameSession.STAGE_MAIN_JOURNEY
    session.turn_number = 1
    session.active_player = players[0]
    session.started_at = timezone.now()
    session.turn_started_at = session.started_at
    session.save(
        update_fields=[
            "status",
            "stage",
            "turn_number",
            "active_player",
            "started_at",
            "turn_started_at",
            "updated_at",
        ]
    )
    session.players.update(has_entered_main_board=True)

    record_event(
        session,
        GameEvent.TYPE_STARTED,
        {"player_count": len(players)},
        actor=players[0],
    )
    logger.info("session_started", extra={"session_id": str(session.id)})
    return session


def leave_session(*, session: GameSession, user) -> GameSession:
    """
    Give up a seat.

    The table survives the host walking away: the next seat is promoted rather
    than the round being abandoned mid-play.
    """
    player = session.players.filter(user=user).first()
    if player is None:
        return session

    was_active = session.active_player_id == player.id
    was_host = player.is_host

    player.delete()
    remaining = list(session.players.order_by("turn_order"))

    if not remaining:
        session.status = GameSession.STATUS_COMPLETED
        session.completed_at = timezone.now()
        session.active_player = None
        session.pending_card = None
    else:
        # Re-seat so turn_order stays a dense 0..n-1 range.
        for index, seat in enumerate(remaining):
            if seat.turn_order != index:
                seat.turn_order = index
                seat.save(update_fields=["turn_order", "updated_at"])

        if was_host:
            new_host = remaining[0]
            new_host.is_host = True
            new_host.save(update_fields=["is_host", "updated_at"])
            session.host_id = new_host.user_id

        if was_active and session.status == GameSession.STATUS_ACTIVE:
            session.pending_card = None
            _advance_turn(session, leaving_player_order=player.turn_order)
        elif was_active:
            session.active_player = remaining[0]

    session.save()
    record_event(
        session,
        GameEvent.TYPE_PLAYER_LEFT,
        {"player_id": str(player.id), "display_name": user.display_name},
    )
    return session


# --------------------------------------------------------------------------- #
# Turns
# --------------------------------------------------------------------------- #


def _require_turn(session: GameSession, user) -> Player:
    if session.status != GameSession.STATUS_ACTIVE:
        raise DomainError("That round isn't in play.")
    player = session.players.filter(user=user).first()
    if player is None:
        raise DomainError("You aren't seated at this table.")
    if session.active_player_id != player.id:
        raise DomainError("It isn't your turn yet.")
    return player


def _draw_card(session: GameSession, player: Player) -> Card | None:
    """
    Draw from the session's deck.

    Cards a player added to a built-in deck stay private to them, so the pool is
    the stock cards plus the drawing player's own.
    """
    pool = Card.objects.filter(deck_id=session.deck_id).playable().visible_to(player.user)
    # `ORDER BY RANDOM()` scans the whole pool; picking an offset costs one
    # cheap COUNT and one indexed fetch, which stays flat as decks grow.
    total = pool.count()
    if total == 0:
        return None
    return pool.order_by("created_at", "id")[secrets.randbelow(total)]


def _next_seat(session: GameSession, from_order: int, seats: list[Player]) -> Player | None:
    """
    The next seat that still has holes to play, consuming any skip along the way.

    Returns None when everyone has finished, which ends the round.
    """
    count = len(seats)
    for step in range(1, count + 1):
        candidate = seats[(from_order + step) % count]
        if candidate.has_finished:
            continue
        if candidate.skip_next_turn:
            candidate.skip_next_turn = False
            candidate.save(update_fields=["skip_next_turn", "updated_at"])
            continue
        return candidate
    return None


def _advance_turn(session: GameSession, *, leaving_player_order: int | None = None) -> None:
    """Hand the turn to the next eligible seat, or complete the round."""
    seats = list(session.players.order_by("turn_order"))
    if not seats:
        session.active_player = None
        return

    if leaving_player_order is not None:
        # The seat that vacated was `leaving_player_order`; after re-seating,
        # whoever now holds that index is next up.
        from_order = (leaving_player_order - 1) % len(seats)
    else:
        current = session.active_player
        from_order = current.turn_order if current else -1

    nxt = _next_seat(session, from_order, seats)
    if nxt is None:
        _complete(session, winner=max(seats, key=lambda p: (p.position, -p.score)))
        return

    session.active_player = nxt
    session.turn_number += 1
    session.turn_started_at = timezone.now()


def _complete(session: GameSession, *, winner: Player | None) -> None:
    session.status = GameSession.STATUS_COMPLETED
    session.completed_at = timezone.now()
    session.winner = winner
    session.active_player = None
    session.pending_card = None
    session.turn_started_at = None


def take_swing(*, session: GameSession, user) -> TurnOutcome:
    """
    Roll, move, and draw -- the "Take Swing" action.

    Mirrors the client mock: a swing always costs a stroke, reaching the last
    hole wins immediately, and anything short of it draws a card to resolve.
    """
    player = _require_turn(session, user)
    if session.pending_card_id is not None:
        raise DomainError("Resolve the card in front of you first.")
    if player.has_finished:
        raise DomainError("You've already finished the course.")

    value = roll_die()
    player.score += STROKE
    player.position = min(settings.TOTAL_HOLES, player.position + value)
    player.has_entered_main_board = True
    player.last_seen_at = timezone.now()
    player.save(
        update_fields=[
            "score",
            "position",
            "has_entered_main_board",
            "last_seen_at",
            "updated_at",
        ]
    )

    session.last_roll = value

    drawn: Card | None = None
    if player.has_finished:
        _complete(session, winner=player)
    else:
        drawn = _draw_card(session, player)
        session.pending_card = drawn
        if drawn is None:
            # An empty deck shouldn't strand the table on a phantom card.
            _advance_turn(session)
        else:
            session.turn_started_at = timezone.now()

    session.save()

    payload = {
        "value": value,
        "position": player.position,
        "card_id": str(drawn.id) if drawn else None,
    }
    record_event(session, GameEvent.TYPE_ROLLED, payload, actor=player)
    return TurnOutcome(session=session, event_type=GameEvent.TYPE_ROLLED, payload=payload)


def resolve_card(*, session: GameSession, user, choice_index: int | None) -> TurnOutcome:
    """
    Settle the pending card and pass the turn on.

    A question answered right is a birdie, wrong is a bogey, and declining to
    answer ("Use Life" in the card modal, which sends no choice) is par.
    """
    player = _require_turn(session, user)
    card = session.pending_card
    if card is None:
        raise DomainError("There's no card to resolve.")

    correct: bool | None = None
    awarded = 0

    # `correct` stays None when the card isn't a question or the player passed
    # on it -- which is what keeps "Use Life" scoring par rather than a bogey.
    if (
        card.type == Card.TYPE_QUESTION
        and card.correct_option_index is not None
        and choice_index is not None
    ):
        correct = choice_index == card.correct_option_index
        player.score += BIRDIE if correct else BOGEY

    effect = card.effect or {}
    move = int(effect.get("move") or 0)
    if move:
        player.position = max(0, min(settings.TOTAL_HOLES, player.position + move))
    if effect.get("skip_turn"):
        player.skip_next_turn = True

    # Points are the reward for engaging: automatic on scripture and challenge
    # cards, earned on a question only by answering it right.
    points = int(effect.get("points") or 0)
    if points and correct is not False:
        awarded = points
        _award_points(player.user, awarded)

    player.last_seen_at = timezone.now()
    player.save(
        update_fields=[
            "score",
            "position",
            "skip_next_turn",
            "last_seen_at",
            "updated_at",
        ]
    )

    session.pending_card = None

    if player.has_finished:
        _complete(session, winner=player)
    else:
        _advance_turn(session)
    session.save()

    payload = {
        "card_id": str(card.id),
        "choice_index": choice_index,
        "correct": correct,
        "points_awarded": awarded,
    }
    record_event(session, GameEvent.TYPE_CARD_RESOLVED, payload, actor=player)
    if session.status == GameSession.STATUS_COMPLETED:
        record_event(
            session,
            GameEvent.TYPE_COMPLETED,
            {"winner_id": str(session.winner_id) if session.winner_id else None},
        )
    return TurnOutcome(
        session=session, event_type=GameEvent.TYPE_CARD_RESOLVED, payload=payload
    )


def skip_stalled_turn(*, session: GameSession, user) -> TurnOutcome:
    """
    Move past a player who has stopped responding.

    Any seated player may call this, but only after the turn clock has run out,
    so one disconnected phone can't hold a family's game night hostage.
    """
    if session.status != GameSession.STATUS_ACTIVE:
        raise DomainError("That round isn't in play.")
    if not session.players.filter(user=user).exists():
        raise DomainError("You aren't seated at this table.")
    if not session.turn_expired:
        raise DomainError("Give them a moment -- their turn hasn't run out yet.")

    stalled = session.active_player
    session.pending_card = None
    _advance_turn(session)
    session.save()

    payload = {"skipped_player_id": str(stalled.id) if stalled else None}
    record_event(session, GameEvent.TYPE_TURN_SKIPPED, payload, actor=stalled)
    return TurnOutcome(
        session=session, event_type=GameEvent.TYPE_TURN_SKIPPED, payload=payload
    )


def _award_points(user, points: int) -> None:
    """
    Credit points and XP without reading them first.

    An F() update is atomic in the database, so two tables resolving cards for
    the same player at once can't lose one of the awards to a stale read.
    """
    from django.db.models import F

    type(user).objects.filter(pk=user.pk).update(
        points=F("points") + points, xp=F("xp") + points
    )
