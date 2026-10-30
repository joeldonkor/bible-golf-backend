"""
The authoritative rules of Bible Golf.

Two-phase game:
  Phase 1 — Growth Ladder: players must roll exactly LADDER_ROLL_TO_ENTER (6)
             to advance one step. After LADDER_STEPS (7) steps the player enters
             the main board. No cards are drawn during this phase.
  Phase 2 — Main Board: any roll moves the player that many spaces (1-68).
             Odd positions draw a positive card; even positions draw a negative
             card. First to reach TOTAL_SPACES (68) wins.

Every function assumes the caller holds a row lock on the session (see
`apps.common.db.locked`) -- these are read-modify-write sequences, and without
the lock two players tapping at the same instant would both read the same board
and one update would vanish.
"""

import logging
import random
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import ConflictError, DomainError
from apps.decks.models import Card, Deck

from .models import GameEvent, GameSession, Player

logger = logging.getLogger(__name__)


def _get_tile_tone(position: int) -> str:
    """Odd positions are positive tiles; even positions are negative tiles."""
    return Card.CARD_TONE_POSITIVE if position % 2 == 1 else Card.CARD_TONE_NEGATIVE


def _draw_card_by_tone(session: GameSession, tone: str) -> Card | None:
    """Draw a random card matching the given tone from the session's deck."""
    pool = list(session.deck.cards.filter(is_active=True, card_tone=tone))
    if not pool:
        # Fallback: any active card from the deck.
        pool = list(session.deck.cards.filter(is_active=True))
    if not pool:
        return None
    return random.choice(pool)


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
    session.stage = GameSession.STAGE_GROWTH_LADDER
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
    # All players start on the ladder, position 0.
    session.players.update(has_entered_main_board=False, ladder_position=0, position=0)

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
        _complete(session)
        return

    session.active_player = nxt
    session.turn_number += 1
    session.turn_started_at = timezone.now()


def _complete(session: GameSession) -> None:
    # Winner = first player who reached TOTAL_SPACES; fallback = furthest along.
    finished = (
        session.players.filter(position__gte=settings.TOTAL_SPACES)
        .order_by("turn_order")
        .first()
    )
    winner = finished or session.players.order_by("-position", "turn_order").first()
    session.status = GameSession.STATUS_COMPLETED
    session.completed_at = timezone.now()
    session.winner = winner
    session.active_player = None
    session.pending_card = None
    session.turn_started_at = None


def take_swing(*, session: GameSession, user) -> TurnOutcome:
    """
    Roll the die and advance the player.

    Ladder phase: only a roll of LADDER_ROLL_TO_ENTER (6) moves the player one
    step up the ladder. Any other roll passes the turn with no movement.

    Main board phase: any roll moves the player that many spaces. Landing on an
    odd position draws a positive card; even draws a negative card.
    """
    player = _require_turn(session, user)
    if session.pending_card_id is not None:
        raise DomainError("Resolve the card in front of you first.")
    if player.has_finished:
        raise DomainError("You've already finished the course.")

    value = roll_die()
    session.last_roll = value

    # ------------------------------------------------------------------ #
    # LADDER PHASE
    # ------------------------------------------------------------------ #
    if not player.has_entered_main_board:
        moved = value == settings.LADDER_ROLL_TO_ENTER
        if moved:
            player.ladder_position = min(settings.LADDER_STEPS, player.ladder_position + 1)
            if player.ladder_position >= settings.LADDER_STEPS:
                player.has_entered_main_board = True
                # Switch stage once the first player steps onto the board.
                if session.stage == GameSession.STAGE_GROWTH_LADDER:
                    session.stage = GameSession.STAGE_MAIN_JOURNEY
        player.last_seen_at = timezone.now()
        player.save(
            update_fields=[
                "ladder_position",
                "has_entered_main_board",
                "last_seen_at",
                "updated_at",
            ]
        )
        session.save(update_fields=["last_roll", "stage", "updated_at"])
        _advance_turn(session)
        session.save(
            update_fields=["active_player", "turn_number", "turn_started_at", "updated_at"]
        )
        payload = {
            "value": value,
            "phase": "ladder",
            "ladder_position": player.ladder_position,
            "moved": moved,
        }
        record_event(session, GameEvent.TYPE_ROLLED, payload, actor=player)
        return TurnOutcome(session=session, event_type=GameEvent.TYPE_ROLLED, payload=payload)

    # ------------------------------------------------------------------ #
    # MAIN BOARD PHASE
    # ------------------------------------------------------------------ #
    new_pos = min(settings.TOTAL_SPACES, player.position + value)
    player.position = new_pos
    player.last_seen_at = timezone.now()
    player.save(update_fields=["position", "last_seen_at", "updated_at"])

    drawn: Card | None = None
    if player.has_finished:
        _complete(session)
        session.save()
    else:
        tone = _get_tile_tone(new_pos)
        # Burn a shield charge instead of drawing a negative card.
        if tone == Card.CARD_TONE_NEGATIVE and player.skip_next_obstacle > 0:
            player.skip_next_obstacle -= 1
            player.save(update_fields=["skip_next_obstacle", "last_seen_at", "updated_at"])
            drawn = None
        else:
            drawn = _draw_card_by_tone(session, tone)
        session.pending_card = drawn
        if drawn is None:
            _advance_turn(session)
        else:
            session.turn_started_at = timezone.now()
        session.save()

    payload = {
        "value": value,
        "phase": "board",
        "position": new_pos,
        "card_id": str(drawn.id) if drawn else None,
    }
    record_event(session, GameEvent.TYPE_ROLLED, payload, actor=player)
    return TurnOutcome(session=session, event_type=GameEvent.TYPE_ROLLED, payload=payload)


def resolve_card(*, session: GameSession, user, choice_index: int | None) -> TurnOutcome:
    """
    Settle the pending card and pass the turn on.

    For question cards a correct answer earns XP; wrong or skipped ("Use Life")
    earns nothing. Win condition is position-only -- not score-based.
    """
    player = _require_turn(session, user)
    card = session.pending_card
    if card is None:
        raise DomainError("There's no card to resolve.")

    correct: bool | None = None
    awarded = 0

    if (
        card.type == Card.TYPE_QUESTION
        and card.correct_option_index is not None
        and choice_index is not None
    ):
        correct = choice_index == card.correct_option_index

    effect = card.effect or {}
    move = int(effect.get("move") or 0)
    if move:
        player.position = max(1, min(settings.TOTAL_SPACES, player.position + move))
    if effect.get("skip_turn"):
        player.skip_next_turn = True
    skip_obstacle = int(effect.get("skip_obstacle") or 0)
    if skip_obstacle:
        player.skip_next_obstacle = min(10, player.skip_next_obstacle + skip_obstacle)

    # Award XP/points for engaging: automatic on most cards, questions only on correct.
    points = int(effect.get("points") or 0)
    if points and correct is not False:
        awarded = points
        _award_points(player.user, awarded)

    player.last_seen_at = timezone.now()
    player.save(
        update_fields=[
            "position",
            "skip_next_turn",
            "skip_next_obstacle",
            "last_seen_at",
            "updated_at",
        ]
    )

    session.pending_card = None

    if player.has_finished:
        _complete(session)
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
