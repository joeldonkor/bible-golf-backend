"""Decks ("scripture courses") and the cards drawn from them during a round."""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import BaseModel


class DeckQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Built-in decks, plus the custom ones this user owns."""
        return self.filter(Q(is_custom=False) | Q(owner=user))

    def with_card_count(self):
        return self.annotate(card_count=models.Count("cards", filter=Q(cards__is_active=True)))


class Deck(BaseModel):
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, default="")
    # `asset://<key>` for bundled art or an absolute https URL.
    cover_url = models.CharField(max_length=500, blank=True, default="")
    is_custom = models.BooleanField(default=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="decks",
    )

    objects = DeckQuerySet.as_manager()

    class Meta:
        ordering = ("is_custom", "name")
        constraints = [
            # A built-in deck has no owner; a custom one always does.
            models.CheckConstraint(
                condition=Q(is_custom=False, owner__isnull=True)
                | Q(is_custom=True, owner__isnull=False),
                name="deck_owner_matches_is_custom",
            ),
            models.UniqueConstraint(
                fields=("owner", "name"),
                condition=Q(owner__isnull=False),
                name="deck_unique_name_per_owner",
            ),
        ]
        indexes = [models.Index(fields=("is_custom", "owner"), name="deck_visibility_idx")]

    def __str__(self) -> str:
        return self.name


class CardQuerySet(models.QuerySet):
    def playable(self):
        return self.filter(is_active=True)

    def visible_to(self, user):
        """
        Stock cards, plus the ones this user added.

        A player may add a card to a built-in deck; it stays private to them
        rather than leaking into everyone else's copy of that deck.
        """
        return self.filter(Q(created_by__isnull=True) | Q(created_by=user))


class Card(BaseModel):
    TYPE_SCRIPTURE = "scripture"
    TYPE_QUESTION = "question"
    TYPE_CHALLENGE = "challenge"
    TYPE_REWARD = "reward"
    TYPE_PENALTY = "penalty"
    TYPE_CHOICES = (
        (TYPE_SCRIPTURE, "Scripture"),
        (TYPE_QUESTION, "Question"),
        (TYPE_CHALLENGE, "Challenge"),
        (TYPE_REWARD, "Reward"),
        (TYPE_PENALTY, "Penalty"),
    )

    RARITY_CHOICES = (
        ("common", "Common"),
        ("rare", "Rare"),
        ("epic", "Epic"),
        ("legendary", "Legendary"),
    )

    # Default effects by type, applied when the client doesn't send one (the
    # card creator screen doesn't). Keys are snake_case in storage and reach the
    # client camelised, matching `CardEffect`.
    DEFAULT_EFFECTS = {
        TYPE_SCRIPTURE: {"move": 1, "points": 10},
        TYPE_QUESTION: {"points": 15},
        TYPE_CHALLENGE: {"points": 20},
        TYPE_REWARD: {"move": 2, "points": 15},
        TYPE_PENALTY: {"move": -2, "points": 0},
    }

    CARD_TONE_POSITIVE = "positive"
    CARD_TONE_NEGATIVE = "negative"
    CARD_TONE_CHOICES = [
        (CARD_TONE_POSITIVE, "Positive"),
        (CARD_TONE_NEGATIVE, "Negative"),
    ]

    deck = models.ForeignKey(Deck, on_delete=models.CASCADE, related_name="cards")
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    rarity = models.CharField(max_length=16, choices=RARITY_CHOICES, default="common")
    card_tone = models.CharField(
        max_length=10, choices=CARD_TONE_CHOICES, default=CARD_TONE_POSITIVE
    )
    title = models.CharField(max_length=120)
    prompt = models.TextField()
    reference = models.CharField(max_length=80, blank=True, default="")
    # Null for non-question cards; a list of 2-6 strings otherwise.
    options = models.JSONField(null=True, blank=True)
    correct_option_index = models.PositiveSmallIntegerField(null=True, blank=True)
    art_url = models.CharField(max_length=500, blank=True, default="")
    effect = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="cards",
    )
    is_active = models.BooleanField(default=True)

    objects = CardQuerySet.as_manager()

    class Meta:
        ordering = ("created_at",)
        constraints = [
            # A question without a correct answer can't be scored.
            models.CheckConstraint(
                condition=~Q(type="question")
                | Q(options__isnull=False, correct_option_index__isnull=False),
                name="card_question_requires_answer",
            ),
        ]
        indexes = [
            # The draw pool lookup: deck + active + visible.
            models.Index(
                fields=("deck", "is_active", "created_by"), name="card_draw_pool_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.type})"

    def save(self, *args, **kwargs):
        if not self.effect:
            self.effect = dict(self.DEFAULT_EFFECTS.get(self.type, {}))
        super().save(*args, **kwargs)
