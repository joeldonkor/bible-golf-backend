"""Serializers for the client's `Deck`, `Card` and card-creation payloads."""

from rest_framework import serializers

from .models import Card, Deck

# Art references we will store. `asset://<key>` resolves to bundled artwork on
# the device; anything else must be a URL every player's phone can fetch.
ALLOWED_ART_SCHEMES = ("asset://", "http://", "https://")

ART_HELP = (
    "Must be an 'asset://<key>' reference or an absolute http(s) URL. "
    "Upload a picked image to POST /api/uploads/card-art/ first and send the "
    "url it returns -- a local file:// URI only exists on the device that "
    "picked it, so nobody else at the table could load the art."
)


def validate_art_reference(value: str) -> str:
    value = (value or "").strip()
    if value and not value.startswith(ALLOWED_ART_SCHEMES):
        raise serializers.ValidationError(ART_HELP)
    return value


class CardArtUploadSerializer(serializers.Serializer):
    """Documents the multipart body of `POST /api/uploads/card-art/`."""

    file = serializers.ImageField(write_only=True)


class CardArtResultSerializer(serializers.Serializer):
    """What that upload returns: the URL to send back as the card's `artUrl`."""

    url = serializers.URLField(read_only=True)


class CardSerializer(serializers.ModelSerializer):
    """Mirrors `src/types/cards.ts#Card`."""

    deck_id = serializers.UUIDField(read_only=True)
    reference = serializers.SerializerMethodField()
    art_url = serializers.SerializerMethodField()

    class Meta:
        model = Card
        fields = (
            "id",
            "deck_id",
            "type",
            "rarity",
            "card_tone",
            "title",
            "prompt",
            "reference",
            "options",
            "correct_option_index",
            "art_url",
            "effect",
        )
        read_only_fields = fields

    def get_reference(self, obj: Card) -> str | None:
        return obj.reference or None

    def get_art_url(self, obj: Card) -> str | None:
        return obj.art_url or None


class DeckSerializer(serializers.ModelSerializer):
    """Mirrors `src/types/cards.ts#Deck`."""

    card_count = serializers.IntegerField(read_only=True)
    cover_url = serializers.SerializerMethodField()
    owner_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Deck
        fields = (
            "id",
            "name",
            "description",
            "cover_url",
            "card_count",
            "is_custom",
            "owner_id",
            "updated_at",
        )
        read_only_fields = fields

    def get_cover_url(self, obj: Deck) -> str | None:
        return obj.cover_url or None


class CreateDeckSerializer(serializers.ModelSerializer):
    """`POST /api/decks/` -- the "New Theme" form in Deck Master."""

    class Meta:
        model = Deck
        fields = ("name", "description", "cover_url")
        extra_kwargs = {
            "name": {"min_length": 2, "max_length": 80},
            "description": {"required": False, "allow_blank": True},
            "cover_url": {"required": False, "allow_blank": True},
        }

    def validate_cover_url(self, value: str) -> str:
        return validate_art_reference(value)

    def create(self, validated_data) -> Deck:
        # Every deck a player creates is theirs; built-in decks are seeded.
        return Deck.objects.create(
            owner=self.context["request"].user, is_custom=True, **validated_data
        )


class CreateCardSerializer(serializers.ModelSerializer):
    """
    `POST /api/cards/` -- the inline card creator.

    The client sends only what the form collects, so rarity and effect are
    filled in server-side from the card's type.
    """

    deck_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = Card
        fields = (
            "deck_id",
            "type",
            "title",
            "prompt",
            "reference",
            "options",
            "correct_option_index",
            "art_url",
            "effect",
            "rarity",
        )
        extra_kwargs = {
            "title": {"min_length": 2, "max_length": 120},
            "prompt": {"min_length": 4},
            "reference": {"required": False, "allow_blank": True},
            "art_url": {"required": False, "allow_blank": True},
            "effect": {"required": False},
            "rarity": {"required": False},
        }

    def validate_art_url(self, value: str) -> str:
        return validate_art_reference(value)

    def validate_deck_id(self, value):
        user = self.context["request"].user
        deck = Deck.objects.visible_to(user).filter(pk=value).first()
        if deck is None:
            raise serializers.ValidationError("That deck doesn't exist.")
        self._deck = deck
        return value

    def validate_options(self, value):
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("Options must be a list of strings.")
        cleaned = [v.strip() for v in value if v and v.strip()]
        if cleaned and len(cleaned) < 2:
            raise serializers.ValidationError("Provide at least two answer options.")
        if len(cleaned) > 6:
            raise serializers.ValidationError("A card can hold at most six options.")
        return cleaned or None

    def validate_effect(self, value):
        if not value:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Effect must be an object.")
        allowed = {"move", "points", "skip_turn"}
        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError(
                f"Unknown effect keys: {', '.join(sorted(unknown))}."
            )
        # Clamp so a crafted card can't teleport a player across the board.
        if "move" in value:
            value["move"] = max(-6, min(6, int(value["move"])))
        if "points" in value:
            value["points"] = max(0, min(100, int(value["points"])))
        return value

    def validate(self, attrs):
        if attrs.get("type") == Card.TYPE_QUESTION:
            options = attrs.get("options")
            if not options:
                raise serializers.ValidationError(
                    {"options": "Question cards need answer options."}
                )
            index = attrs.get("correct_option_index")
            if index is None or index >= len(options):
                raise serializers.ValidationError(
                    {"correctOptionIndex": "Point at one of the options."}
                )
        else:
            # Only questions are scored against an answer.
            attrs["options"] = None
            attrs["correct_option_index"] = None
        return attrs

    def create(self, validated_data) -> Card:
        validated_data.pop("deck_id", None)
        return Card.objects.create(
            deck=self._deck,
            created_by=self.context["request"].user,
            **validated_data,
        )
