"""Ranking scopes, badge awards, and the level table."""

import pytest

from apps.accounts.levels import LEVEL_THRESHOLDS, level_for_xp, next_threshold
from apps.accounts.models import Congregation
from apps.leaderboard.models import Badge, UserBadge
from apps.leaderboard.services import evaluate_badges

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Levels -- the server-side twin of `src/constants/gamification.ts`
# --------------------------------------------------------------------------- #


def test_level_thresholds_match_the_client():
    assert LEVEL_THRESHOLDS == (
        ("bible_student", 0),
        ("faith_builder", 500),
        ("kingdom_worker", 1_500),
        ("spiritual_guide", 3_000),
        ("faith_mentor", 5_000),
    )


@pytest.mark.parametrize(
    ("xp", "expected"),
    [
        (0, "bible_student"),
        (499, "bible_student"),
        (500, "faith_builder"),
        (1_250, "faith_builder"),
        (1_500, "kingdom_worker"),
        (3_000, "spiritual_guide"),
        (4_999, "spiritual_guide"),
        (5_000, "faith_mentor"),
        (50_000, "faith_mentor"),
    ],
)
def test_level_for_xp(xp, expected):
    assert level_for_xp(xp) == expected


def test_the_top_tier_has_nothing_above_it():
    assert next_threshold("faith_mentor") is None
    assert next_threshold("bible_student") == 500


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #


def test_global_ranks_are_absolute_not_per_page(auth, make_user):
    for index in range(6):
        make_user(
            email=f"p{index}@example.com",
            display_name=f"P{index}",
            points=(index + 1) * 100,
        )
    me = make_user(email="me@example.com", display_name="Me", points=50)

    response = auth(me).get("/api/leaderboard/", {"scope": "global", "pageSize": 2})
    rows = response.json()["results"]

    assert [row["rank"] for row in rows[:2]] == [1, 2]
    assert rows[0]["points"] > rows[1]["points"]

    # Page two keeps counting rather than restarting at 1.
    page_two = (
        auth(me)
        .get("/api/leaderboard/", {"scope": "global", "pageSize": 2, "page": 2})
        .json()["results"]
    )
    assert [row["rank"] for row in page_two[:2]] == [3, 4]


def test_your_own_row_is_appended_when_you_are_off_the_page(auth, make_user):
    for index in range(5):
        make_user(
            email=f"p{index}@example.com",
            display_name=f"P{index}",
            points=(index + 10) * 100,
        )
    me = make_user(email="me@example.com", display_name="Me", points=1)

    rows = (
        auth(me).get("/api/leaderboard/", {"scope": "global", "pageSize": 3}).json()["results"]
    )

    assert len(rows) == 4  # three ranked rows, plus you
    assert rows[-1]["userId"] == str(me.id)
    assert rows[-1]["rank"] == 6


def test_congregation_scope_only_shows_your_own(auth, make_user):
    ours = Congregation.objects.create(name="Grace Chapel", slug="grace-chapel")
    theirs = Congregation.objects.create(name="Hillside", slug="hillside")

    me = make_user(email="me@example.com", display_name="Me", congregation=ours, points=10)
    make_user(email="sib@example.com", display_name="Sibling", congregation=ours, points=20)
    make_user(email="out@example.com", display_name="Outsider", congregation=theirs, points=99)

    rows = auth(me).get("/api/leaderboard/", {"scope": "congregation"}).json()["results"]
    names = [row["displayName"] for row in rows]
    assert names == ["Sibling", "Me"]


def test_congregation_scope_is_empty_rather_than_global_when_unassigned(auth, make_user):
    me = make_user(email="me@example.com", display_name="Me", points=10)
    make_user(email="other@example.com", display_name="Other", points=99)

    rows = auth(me).get("/api/leaderboard/", {"scope": "congregation"}).json()["results"]
    assert rows == []


def test_friends_scope_is_the_people_you_have_played_with(table, host, guest, make_user):
    """No friend list to curate -- sitting at a table together is the signal."""
    _, host_client, _ = table
    stranger = make_user(email="stranger@example.com", display_name="Stranger", points=999)

    rows = host_client.get("/api/leaderboard/", {"scope": "friends"}).json()["results"]
    ids = {row["userId"] for row in rows}

    assert str(guest.id) in ids
    assert str(host.id) in ids
    assert str(stranger.id) not in ids


def test_an_unknown_scope_falls_back_to_global(auth, make_user):
    me = make_user(email="me@example.com", display_name="Me", points=5)
    make_user(email="other@example.com", display_name="Other", points=10)

    rows = auth(me).get("/api/leaderboard/", {"scope": "nonsense"}).json()["results"]
    assert len(rows) == 2


# --------------------------------------------------------------------------- #
# Badges
# --------------------------------------------------------------------------- #


def test_badges_report_earned_state(auth, host):
    earned = Badge.objects.create(
        code="prayer-master",
        name="Prayer Master",
        description="Reach Faith Mentor.",
        icon_name="lock",
        criteria={"type": Badge.CRITERIA_LEVEL, "value": "faith_mentor"},
    )
    Badge.objects.create(
        code="word-watcher",
        name="Word Watcher",
        description="Resolve 7 cards.",
        icon_name="book",
        criteria={"type": Badge.CRITERIA_CARDS, "value": 7},
    )
    UserBadge.objects.create(user=host, badge=earned)

    rows = auth(host).get("/api/leaderboard/badges/").json()["results"]
    by_name = {row["name"]: row["earned"] for row in rows}
    assert by_name == {"Prayer Master": True, "Word Watcher": False}


def test_an_xp_badge_is_awarded_once_the_bar_is_cleared(host):
    Badge.objects.create(
        code="first-steps",
        name="First Steps",
        description="Earn 100 XP.",
        icon_name="star",
        criteria={"type": Badge.CRITERIA_XP, "value": 100},
    )

    assert evaluate_badges(host) == []

    host.xp = 120
    host.save(update_fields=["xp"])
    awarded = evaluate_badges(host)

    assert [badge.code for badge in awarded] == ["first-steps"]
    # And never twice.
    assert evaluate_badges(host) == []


def test_a_level_badge_reads_the_derived_level(host):
    Badge.objects.create(
        code="kingdom-worker",
        name="Kingdom Worker",
        description="Reach Kingdom Worker.",
        icon_name="hammer",
        criteria={"type": Badge.CRITERIA_LEVEL, "value": "kingdom_worker"},
    )
    host.xp = 1_500
    host.save(update_fields=["xp"])

    assert [badge.code for badge in evaluate_badges(host)] == ["kingdom-worker"]


def test_finishing_a_round_awards_the_win_badge(table, host, guest, settings):
    from apps.games.models import Player

    Badge.objects.create(
        code="fairway-champion",
        name="Fairway Champion",
        description="Win a round.",
        icon_name="trophy",
        criteria={"type": Badge.CRITERIA_WINS, "value": 1},
    )

    session_id, host_client, guest_client = table
    state = host_client.get(f"/api/sessions/{session_id}/state/").json()
    mover = Player.objects.select_related("user").get(pk=state["activePlayerId"])
    client = host_client if mover.user_id == host.id else guest_client

    mover.position = settings.TOTAL_HOLES - 1
    mover.save(update_fields=["position"])
    client.post(f"/api/sessions/{session_id}/roll/", format="json")

    assert UserBadge.objects.filter(user=mover.user, badge__code="fairway-champion").exists()
