"""Badges and the records of who has earned them."""

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class Badge(BaseModel):
    """
    An achievement.

    `criteria` is data rather than code so a new badge is a row, not a deploy.
    `apps.leaderboard.services.evaluate_badges` knows how to read each `type`.
    """

    CRITERIA_XP = "xp_at_least"
    CRITERIA_LEVEL = "level_at_least"
    CRITERIA_CARDS = "cards_resolved"
    CRITERIA_SESSIONS = "sessions_played"
    CRITERIA_WINS = "sessions_won"
    CRITERIA_TYPES = (
        CRITERIA_XP,
        CRITERIA_LEVEL,
        CRITERIA_CARDS,
        CRITERIA_SESSIONS,
        CRITERIA_WINS,
    )

    code = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=160)
    # Client-side icon name, e.g. "book", "heart", "church".
    icon_name = models.CharField(max_length=40)
    criteria = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return self.name


class UserBadge(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="badges"
    )
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name="holders")
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "badge"), name="user_badge_unique")
        ]
        indexes = [models.Index(fields=("user", "badge"), name="user_badge_idx")]

    def __str__(self) -> str:
        return f"{self.user_id} earned {self.badge_id}"
