"""Ranking queries and badge evaluation."""

import logging

from django.contrib.auth import get_user_model
from django.db.models import F, Q, Window
from django.db.models.functions import Rank

from apps.accounts.levels import LEVEL_ORDER
from apps.games.models import GameEvent, GameSession, Player

from .models import Badge, UserBadge

logger = logging.getLogger(__name__)

SCOPE_FRIENDS = "friends"
SCOPE_CONGREGATION = "congregation"
SCOPE_GLOBAL = "global"
SCOPES = (SCOPE_FRIENDS, SCOPE_CONGREGATION, SCOPE_GLOBAL)


def scoped_users(*, user, scope: str):
    """The unranked population a scope covers."""
    User = get_user_model()
    base = User.objects.filter(is_active=True)

    if scope == SCOPE_CONGREGATION:
        if user.congregation_id is None:
            # Nobody has been placed in a congregation yet; the honest answer
            # to "how do I rank in mine" is an empty board, not the world's.
            return base.none()
        base = base.filter(congregation_id=user.congregation_id)
    elif scope == SCOPE_FRIENDS:
        # "Friends" are the people you have actually sat at a table with --
        # derived from play, so there is no friend list to curate.
        played_with = (
            Player.objects.filter(session__in=GameSession.objects.filter(players__user=user))
            .exclude(user=user)
            .values_list("user_id", flat=True)
        )
        base = base.filter(Q(pk=user.pk) | Q(pk__in=played_with))

    return base


def ranked_users(*, user, scope: str):
    """
    Users in `scope`, ordered best first and annotated with their rank.

    The rank is a database window over the scoped set, so page 3 shows ranks
    51-75 rather than restarting at 1 -- which a per-page Python counter gets
    wrong the moment anyone scrolls.
    """
    return (
        scoped_users(user=user, scope=scope)
        .annotate(rank=Window(expression=Rank(), order_by=F("points").desc()))
        .order_by("-points", "id")
    )


def rank_of(*, user, scope: str):
    """
    One user's standing in a scope, or None if they aren't in it.

    Filtering the ranked queryset down to a single row would recompute the
    window over that one row and always answer "1", so the rank is counted
    against the full scope instead. Ties share the better rank, matching
    SQL `RANK()`.
    """
    base = scoped_users(user=user, scope=scope)
    row = base.filter(pk=user.pk).first()
    if row is None:
        return None
    row.rank = base.filter(points__gt=row.points).count() + 1
    return row


def badges_for(user):
    """Every active badge, each flagged with whether this user has it."""
    earned = set(UserBadge.objects.filter(user=user).values_list("badge_id", flat=True))
    badges = list(Badge.objects.filter(is_active=True))
    for badge in badges:
        badge.earned = badge.id in earned
    return badges


# --------------------------------------------------------------------------- #
# Badge evaluation
# --------------------------------------------------------------------------- #


def _measure(user, criteria: dict) -> bool:
    kind = criteria.get("type")
    target = criteria.get("value", criteria.get("count", 0))

    if kind == Badge.CRITERIA_XP:
        return user.xp >= int(target)

    if kind == Badge.CRITERIA_LEVEL:
        if target not in LEVEL_ORDER:
            return False
        return LEVEL_ORDER.index(user.level) >= LEVEL_ORDER.index(target)

    if kind == Badge.CRITERIA_CARDS:
        count = GameEvent.objects.filter(
            type=GameEvent.TYPE_CARD_RESOLVED, actor__user=user
        ).count()
        return count >= int(target)

    if kind == Badge.CRITERIA_SESSIONS:
        count = GameSession.objects.filter(
            players__user=user, status=GameSession.STATUS_COMPLETED
        ).count()
        return count >= int(target)

    if kind == Badge.CRITERIA_WINS:
        count = GameSession.objects.filter(winner__user=user).count()
        return count >= int(target)

    logger.warning("unknown_badge_criteria", extra={"criteria": criteria})
    return False


def evaluate_badges(user) -> list[Badge]:
    """
    Award any badge the user now qualifies for. Returns the newly earned ones.

    Called after a round completes rather than on every card, because the
    criteria are cheap to check but not free, and nothing here is time-critical.
    """
    already = set(UserBadge.objects.filter(user=user).values_list("badge_id", flat=True))
    newly: list[Badge] = []

    for badge in Badge.objects.filter(is_active=True).exclude(id__in=already):
        if badge.criteria and _measure(user, badge.criteria):
            _, created = UserBadge.objects.get_or_create(user=user, badge=badge)
            if created:
                newly.append(badge)

    if newly:
        logger.info(
            "badges_awarded",
            extra={
                "user_id": str(user.id),
                "badges": [badge.code for badge in newly],
            },
        )
    return newly
