"""
Seed the built-in decks, cards and badges.

The content mirrors the mobile app's mock fixtures
(`src/services/mock/fixtures.ts`), art references included, so flipping
`EXPO_PUBLIC_USE_MOCKS` to `false` shows the same library rather than an empty
Deck Master. `asset://<key>` references resolve to artwork bundled in the app;
`artSource()` handles an https URL identically, so real uploads slot in later
with no client change.

Idempotent -- safe to run on every deploy.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.decks.models import Card, Deck
from apps.leaderboard.models import Badge

DECKS = [
    {
        "name": "Grace & Peace",
        "description": "Rest in the promises that steady the soul.",
        "cover_url": "asset://course-grace",
    },
    {
        "name": "Strength",
        "description": "Courage for the climb, from Joshua to Paul.",
        "cover_url": "asset://course-strength",
    },
    {
        "name": "Providence",
        "description": "How God provides along the winding way.",
        "cover_url": "asset://course-providence",
    },
    {
        "name": "Wisdom",
        "description": "Proverbs and parables for daily decisions.",
        "cover_url": "asset://course-wisdom",
    },
    {
        "name": "Parables",
        "description": "Timeless stories Jesus told, reimagined for play.",
        "cover_url": "asset://card-lost-sheep",
    },
    {
        "name": "Old Testament",
        "description": "From Genesis to the prophets.",
        "cover_url": "",
    },
]

CARDS = [
    {
        "deck": "Old Testament",
        "type": Card.TYPE_QUESTION,
        "rarity": "common",
        "title": "Complete the Verse",
        "prompt": "In the beginning God created the ______ and the earth.",
        "reference": "Genesis 1:1",
        "options": ["Firmament", "Heavens", "Stars", "Oceans"],
        "correct_option_index": 1,
        "effect": {"points": 15},
    },
    {
        "deck": "Parables",
        "type": Card.TYPE_SCRIPTURE,
        "rarity": "legendary",
        "title": "The Lost Sheep",
        "prompt": "Rejoice with me; I have found my lost sheep.",
        "reference": "Luke 15:6",
        "art_url": "asset://card-lost-sheep",
        "effect": {"move": 3, "points": 10},
    },
    {
        "deck": "Parables",
        "type": Card.TYPE_SCRIPTURE,
        "rarity": "rare",
        "title": "The Mustard Seed",
        "prompt": "Growth from the smallest faith.",
        "reference": "Matthew 13:31",
        "art_url": "asset://card-mustard-seed",
        "effect": {"move": 1, "points": 10},
    },
    {
        "deck": "Parables",
        "type": Card.TYPE_SCRIPTURE,
        "rarity": "epic",
        "title": "The Prodigal Son",
        "prompt": "A journey of unconditional love.",
        "reference": "Luke 15:20",
        "art_url": "asset://card-prodigal-son",
        "effect": {"move": 2, "points": 10},
    },
    {
        "deck": "Grace & Peace",
        "type": Card.TYPE_CHALLENGE,
        "rarity": "rare",
        "title": "Memory Verse",
        "prompt": "Recite Psalm 23:1 aloud to the table.",
        "reference": "Psalm 23:1",
        "effect": {"points": 20},
    },
    {
        "deck": "Grace & Peace",
        "type": Card.TYPE_QUESTION,
        "rarity": "common",
        "title": "Complete the Verse",
        "prompt": "Peace I leave with you; my ______ I give you.",
        "reference": "John 14:27",
        "options": ["Peace", "Spirit", "Word", "Joy"],
        "correct_option_index": 0,
        "effect": {"points": 15},
    },
    {
        "deck": "Strength",
        "type": Card.TYPE_QUESTION,
        "rarity": "common",
        "title": "Complete the Verse",
        "prompt": "Be strong and ______; do not be afraid.",
        "reference": "Joshua 1:9",
        "options": ["Faithful", "Courageous", "Steadfast", "Bold"],
        "correct_option_index": 1,
        "effect": {"points": 15},
    },
    {
        "deck": "Providence",
        "type": Card.TYPE_SCRIPTURE,
        "rarity": "rare",
        "title": "Daily Bread",
        "prompt": (
            "And my God will meet all your needs according to the riches of "
            "his glory in Christ Jesus."
        ),
        "reference": "Philippians 4:19",
        "effect": {"move": 1, "points": 10},
    },
    {
        "deck": "Wisdom",
        "type": Card.TYPE_QUESTION,
        "rarity": "common",
        "title": "Complete the Verse",
        "prompt": "The fear of the Lord is the beginning of ______.",
        "reference": "Proverbs 9:10",
        "options": ["Wisdom", "Peace", "Faith", "Life"],
        "correct_option_index": 0,
        "effect": {"points": 15},
    },
    {
        "deck": "Wisdom",
        "type": Card.TYPE_CHALLENGE,
        "rarity": "common",
        "title": "Screen Sabbath",
        "prompt": "Share one way you can rest from your phone this week.",
        "effect": {"points": 10},
    },
]

BADGES = [
    {
        "code": "word-watcher",
        "name": "Word Watcher",
        "description": "Resolve 7 scripture cards.",
        "icon_name": "book",
        "criteria": {"type": Badge.CRITERIA_CARDS, "value": 7},
        "sort_order": 1,
    },
    {
        "code": "giving-heart",
        "name": "Giving Heart",
        "description": "Complete 5 challenge cards.",
        "icon_name": "heart",
        "criteria": {"type": Badge.CRITERIA_CARDS, "value": 5},
        "sort_order": 2,
    },
    {
        "code": "sunday-regular",
        "name": "Sunday Regular",
        "description": "Finish 4 rounds with your table.",
        "icon_name": "church",
        "criteria": {"type": Badge.CRITERIA_SESSIONS, "value": 4},
        "sort_order": 3,
    },
    {
        "code": "prayer-master",
        "name": "Prayer Master",
        "description": "Reach the Faith Mentor level.",
        "icon_name": "lock",
        "criteria": {"type": Badge.CRITERIA_LEVEL, "value": "faith_mentor"},
        "sort_order": 4,
    },
    {
        "code": "fairway-champion",
        "name": "Fairway Champion",
        "description": "Win your first round.",
        "icon_name": "trophy",
        "criteria": {"type": Badge.CRITERIA_WINS, "value": 1},
        "sort_order": 5,
    },
]


class Command(BaseCommand):
    help = "Create or refresh the built-in decks, cards and badges."

    @transaction.atomic
    def handle(self, *args, **options):
        decks: dict[str, Deck] = {}
        for spec in DECKS:
            deck, created = Deck.objects.get_or_create(
                name=spec["name"],
                is_custom=False,
                owner=None,
                defaults={
                    "description": spec["description"],
                    "cover_url": spec["cover_url"],
                },
            )
            if not created:
                deck.description = spec["description"]
                deck.cover_url = spec["cover_url"]
                deck.save(update_fields=["description", "cover_url", "updated_at"])
            decks[spec["name"]] = deck

        card_count = 0
        for spec in CARDS:
            spec = dict(spec)
            deck = decks[spec.pop("deck")]
            title = spec.pop("title")
            Card.objects.update_or_create(
                deck=deck,
                title=title,
                created_by=None,
                prompt=spec["prompt"],
                defaults=spec,
            )
            card_count += 1

        for spec in BADGES:
            Badge.objects.update_or_create(code=spec["code"], defaults=spec)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(DECKS)} decks, {card_count} cards, {len(BADGES)} badges."
            )
        )
