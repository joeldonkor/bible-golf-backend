"""
Gamification tiers.

These thresholds are the server-side twin of `src/constants/gamification.ts`.
The client renders labels and progress bars from them, so the two must agree --
`tests/test_levels.py` pins the table so a change here can't drift silently.
"""

from typing import Final

BIBLE_STUDENT: Final = "bible_student"
FAITH_BUILDER: Final = "faith_builder"
KINGDOM_WORKER: Final = "kingdom_worker"
SPIRITUAL_GUIDE: Final = "spiritual_guide"
FAITH_MENTOR: Final = "faith_mentor"

# (level, cumulative XP required) in ascending order.
LEVEL_THRESHOLDS: Final[tuple[tuple[str, int], ...]] = (
    (BIBLE_STUDENT, 0),
    (FAITH_BUILDER, 500),
    (KINGDOM_WORKER, 1_500),
    (SPIRITUAL_GUIDE, 3_000),
    (FAITH_MENTOR, 5_000),
)

LEVEL_CHOICES: Final = tuple(
    (key, key.replace("_", " ").title()) for key, _ in LEVEL_THRESHOLDS
)

LEVEL_ORDER: Final = tuple(key for key, _ in LEVEL_THRESHOLDS)


def level_for_xp(xp: int) -> str:
    """The highest tier whose threshold `xp` has reached."""
    level = LEVEL_THRESHOLDS[0][0]
    for key, minimum in LEVEL_THRESHOLDS:
        if xp >= minimum:
            level = key
        else:
            break
    return level


def next_threshold(level: str) -> int | None:
    """XP needed for the tier above `level`, or None at the top."""
    index = LEVEL_ORDER.index(level)
    if index + 1 >= len(LEVEL_THRESHOLDS):
        return None
    return LEVEL_THRESHOLDS[index + 1][1]
