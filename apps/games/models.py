"""Game sessions ("tables"), their seated players, and the event log."""

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel

# Ambiguous glyphs are dropped: a code gets read aloud across a dinner table,
# so O/0 and I/1 would cost more than the 4 bits they buy. 32**6 ~= 1.07e9.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


class GameSessionQuerySet(models.QuerySet):
    def live(self):
        return self.exclude(status=GameSession.STATUS_COMPLETED)

    def for_user(self, user):
        return self.filter(players__user=user)

    def with_related(self):
        """Everything the session/state serializers touch, in one round trip."""
        return self.select_related("deck", "pending_card", "host").prefetch_related(
            models.Prefetch(
                "players",
                queryset=Player.objects.select_related("user").order_by("turn_order"),
            )
        )


class GameSession(BaseModel):
    STATUS_LOBBY = "lobby"
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = (
        (STATUS_LOBBY, "Lobby"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
    )

    STAGE_GROWTH_LADDER = "growth_ladder"
    STAGE_MAIN_JOURNEY = "main_journey"
    STAGE_CHOICES = (
        (STAGE_GROWTH_LADDER, "Growth ladder"),
        (STAGE_MAIN_JOURNEY, "Main journey"),
    )

    code = models.CharField(max_length=CODE_LENGTH, unique=True, db_index=True)
    name = models.CharField(max_length=40)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hosted_sessions"
    )
    deck = models.ForeignKey("decks.Deck", on_delete=models.PROTECT, related_name="sessions")

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_LOBBY)
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default=STAGE_GROWTH_LADDER)
    max_players = models.PositiveSmallIntegerField(default=4)

    # ---- live turn state -------------------------------------------------- #
    turn_number = models.PositiveIntegerField(default=0)
    last_roll = models.PositiveSmallIntegerField(null=True, blank=True)
    active_player = models.ForeignKey(
        "Player", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The card drawn by the active player's landing, awaiting resolution.
    pending_card = models.ForeignKey(
        "decks.Card", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    winner = models.ForeignKey(
        "Player", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    turn_started_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Monotonic counter bumped on every mutation. Websocket clients drop frames
    # older than the last one they applied, so a reordered broadcast can never
    # rewind the board.
    version = models.PositiveIntegerField(default=0)

    objects = GameSessionQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "-created_at"), name="session_status_idx"),
            models.Index(fields=("host", "status"), name="session_host_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.code}]"

    @classmethod
    def create_with_code(cls, **fields) -> "GameSession":
        """
        Create with a unique join code.

        The uniqueness constraint is the real arbiter; this just retries the
        handful of times a collision could plausibly happen before giving up.
        """
        from django.db import IntegrityError, transaction

        for _ in range(8):
            try:
                with transaction.atomic():
                    return cls.objects.create(code=generate_code(), **fields)
            except IntegrityError:
                continue
        raise RuntimeError("Could not allocate a unique table code.")

    @property
    def is_full(self) -> bool:
        return self.players.count() >= self.max_players

    @property
    def turn_expired(self) -> bool:
        if self.turn_started_at is None:
            return False
        elapsed = (timezone.now() - self.turn_started_at).total_seconds()
        return elapsed > settings.TURN_TIMEOUT_SECONDS


class Player(BaseModel):
    """
    One seat at a table.

    Note for anyone matching this against the client: `Session.hostId` is a
    *Player* id, not a user id -- `LobbyScreen` looks the host up with
    `players.find(p => p.id === session.hostId)`.
    """

    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="players")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="player_seats"
    )

    turn_order = models.PositiveSmallIntegerField()
    position = models.PositiveSmallIntegerField(default=0)
    # Golf scoring: strokes relative to par, so it can legitimately go negative.
    score = models.SmallIntegerField(default=0)
    is_host = models.BooleanField(default=False)
    has_entered_main_board = models.BooleanField(default=False)
    skip_next_turn = models.BooleanField(default=False)

    # Sockets held open by this player. A phone that backgrounds and resumes
    # briefly holds two, so presence is a count rather than a boolean.
    connection_count = models.PositiveSmallIntegerField(default=0)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("turn_order",)
        constraints = [
            models.UniqueConstraint(
                fields=("session", "user"), name="player_unique_per_session"
            ),
            models.UniqueConstraint(
                fields=("session", "turn_order"), name="player_unique_seat"
            ),
        ]
        indexes = [models.Index(fields=("user", "session"), name="player_user_idx")]

    def __str__(self) -> str:
        return f"{self.user.display_name} @ {self.session.code}"

    @property
    def is_connected(self) -> bool:
        return self.connection_count > 0

    @property
    def has_finished(self) -> bool:
        return self.position >= settings.TOTAL_HOLES


class GameEvent(models.Model):
    """
    Append-only log of everything that happened at a table.

    It is what a reconnecting client replays to catch up, and what makes a
    disputed round auditable after the fact.
    """

    TYPE_CREATED = "session_created"
    TYPE_PLAYER_JOINED = "player_joined"
    TYPE_PLAYER_LEFT = "player_left"
    TYPE_STARTED = "game_started"
    TYPE_ROLLED = "player_rolled"
    TYPE_CARD_DRAWN = "card_drawn"
    TYPE_CARD_RESOLVED = "card_resolved"
    TYPE_TURN_SKIPPED = "turn_skipped"
    TYPE_COMPLETED = "game_completed"

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(GameSession, on_delete=models.CASCADE, related_name="events")
    sequence = models.PositiveIntegerField()
    type = models.CharField(max_length=32)
    actor = models.ForeignKey(
        Player, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sequence",)
        constraints = [
            models.UniqueConstraint(
                fields=("session", "sequence"), name="event_unique_sequence"
            )
        ]
        indexes = [
            models.Index(fields=("session", "-sequence"), name="event_recent_idx"),
        ]

    def __str__(self) -> str:
        return f"#{self.sequence} {self.type}"
