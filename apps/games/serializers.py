"""
Serializers for the client's `Session`, `Player` and `GameState`.

These shapes are a contract with `src/types/game.ts`; `tests/test_contract.py`
asserts the exact key set of each response so a field can't be renamed here
without the test that guards the mobile app going red.
"""

from rest_framework import serializers

from apps.decks.models import Deck
from apps.decks.serializers import CardSerializer

from .models import GameEvent, GameSession, Player


class PlayerSerializer(serializers.ModelSerializer):
    """Mirrors `src/types/game.ts#Player`."""

    user_id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    avatar_url = serializers.SerializerMethodField()
    level = serializers.CharField(source="user.level", read_only=True)
    is_connected = serializers.BooleanField(read_only=True)

    class Meta:
        model = Player
        fields = (
            "id",
            "user_id",
            "display_name",
            "avatar_url",
            "level",
            "position",
            "score",
            "is_host",
            "is_connected",
            "has_entered_main_board",
        )
        read_only_fields = fields

    def get_avatar_url(self, obj: Player) -> str | None:
        return obj.user.avatar_url or None


def _host_player_id(session: GameSession) -> str | None:
    """
    The host's *Player* id.

    `LobbyScreen` resolves the host with `players.find(p => p.id === hostId)`,
    so this is deliberately not the user id.
    """
    for player in session.players.all():
        if player.is_host:
            return str(player.id)
    return None


class SessionSerializer(serializers.ModelSerializer):
    """Mirrors `src/types/game.ts#Session`."""

    host_id = serializers.SerializerMethodField()
    deck_id = serializers.UUIDField(read_only=True)
    players = PlayerSerializer(many=True, read_only=True)

    class Meta:
        model = GameSession
        fields = (
            "id",
            "code",
            "name",
            "host_id",
            "status",
            "stage",
            "players",
            "deck_id",
            "max_players",
            "created_at",
        )
        read_only_fields = fields

    def get_host_id(self, obj: GameSession) -> str | None:
        return _host_player_id(obj)


class GameStateSerializer(serializers.Serializer):
    """
    Mirrors `src/types/game.ts#GameState` -- the payload every turn action
    returns and every websocket frame carries.
    """

    session_id = serializers.UUIDField(source="id", read_only=True)
    status = serializers.CharField(read_only=True)
    stage = serializers.CharField(read_only=True)
    active_player_id = serializers.SerializerMethodField()
    turn_number = serializers.IntegerField(read_only=True)
    last_roll = serializers.IntegerField(read_only=True, allow_null=True)
    pending_card = serializers.SerializerMethodField()
    players = PlayerSerializer(many=True, read_only=True)
    # Not part of the client's type today, but a websocket client needs it to
    # drop frames it has already applied. Extra keys are ignored by the client.
    version = serializers.IntegerField(read_only=True)

    def get_active_player_id(self, obj: GameSession) -> str | None:
        return str(obj.active_player_id) if obj.active_player_id else None

    def get_pending_card(self, obj: GameSession) -> dict | None:
        card = obj.pending_card
        return CardSerializer(card).data if card else None


class CreateSessionSerializer(serializers.Serializer):
    """`POST /api/sessions/` -- the "Create Table" modal."""

    name = serializers.CharField(min_length=2, max_length=40)
    deck_id = serializers.UUIDField()
    max_players = serializers.IntegerField(required=False, min_value=2, max_value=8, default=4)

    def validate_deck_id(self, value):
        deck = Deck.objects.visible_to(self.context["request"].user).filter(pk=value).first()
        if deck is None:
            raise serializers.ValidationError("Pick a scripture course you can play.")
        self.deck = deck
        return value


class JoinSessionSerializer(serializers.Serializer):
    """`POST /api/sessions/join/` -- join by the 6-character table code."""

    code = serializers.CharField(min_length=6, max_length=6)

    def validate_code(self, value: str) -> str:
        return value.strip().upper()


class ResolveCardSerializer(serializers.Serializer):
    """
    `POST /api/sessions/{id}/resolve-card/`.

    The client omits `choiceIndex` for non-questions and for "Use Life", which
    passes on the question at par.
    """

    choice_index = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=5
    )


class GameEventSerializer(serializers.ModelSerializer):
    """The replay log a reconnecting client can catch up from."""

    class Meta:
        model = GameEvent
        fields = ("sequence", "type", "actor", "payload", "created_at")
        read_only_fields = fields
