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
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_NEGATIVE,
        "rarity": "rare",
        "title": "Memory Verse",
        "prompt": "Recite Psalm 23:1 aloud to the table.",
        "reference": "Psalm 23:1",
        "effect": {"points": 20},
    },
    {
        "deck": "Grace & Peace",
        "type": Card.TYPE_QUESTION,
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_POSITIVE,
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
        "card_tone": Card.CARD_TONE_NEGATIVE,
        "rarity": "common",
        "title": "Screen Sabbath",
        "prompt": "Share one way you can rest from your phone this week.",
        "effect": {"points": 10},
    },
]

BIBLE_GOLF_POSITIVE_CARDS = [
    {"title": "Blessing 1", "prompt": "Your faith has moved mountains. Move forward 3 spaces.", "effect": {"move": 3, "points": 10}},
    {"title": "Blessing 2", "prompt": "You shared the good news with a neighbour. Move forward 2 spaces.", "effect": {"move": 2, "points": 10}},
    {"title": "Blessing 3", "prompt": "You attended the meeting faithfully. Move forward 2 spaces.", "effect": {"move": 2, "points": 10}},
    {"title": "Blessing 4", "prompt": "You completed your personal Bible study. Move forward 1 space.", "effect": {"move": 1, "points": 10}},
    {"title": "Blessing 5", "prompt": "You helped a fellow believer in need. Move forward 2 spaces.", "effect": {"move": 2, "points": 10}},
]

BIBLE_GOLF_NEGATIVE_CARDS = [
    {"title": "Trial 1", "prompt": "You missed the meeting this week. Move back 2 spaces.", "effect": {"move": -2, "points": 0}},
    {"title": "Trial 2", "prompt": "You argued with a brother. Move back 1 space.", "effect": {"move": -1, "points": 0}},
    {"title": "Trial 3", "prompt": "You neglected your Bible reading. Move back 2 spaces.", "effect": {"move": -2, "points": 0}},
    {"title": "Trial 4", "prompt": "You were distracted from your ministry. Miss a turn.", "effect": {"skip_turn": True, "points": 0}},
    {"title": "Trial 5", "prompt": "You gave in to a bad habit. Move back 3 spaces.", "effect": {"move": -3, "points": 0}},
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
        # ---- Built-in thematic decks ---------------------------------------- #
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

        # ---- Official Bible Golf deck --------------------------------------- #
        bible_golf_deck, _ = Deck.objects.update_or_create(
            name="Bible Golf",
            owner=None,
            defaults={
                "description": "The official Bible Golf card deck.",
                "is_custom": False,
                "cover_url": "",
            },
        )
        decks["Bible Golf"] = bible_golf_deck

        for spec in BIBLE_GOLF_POSITIVE_CARDS:
            Card.objects.update_or_create(
                deck=bible_golf_deck,
                title=spec["title"],
                created_by=None,
                defaults={
                    "type": Card.TYPE_REWARD,
                    "card_tone": Card.CARD_TONE_POSITIVE,
                    "prompt": spec["prompt"],
                    "effect": spec["effect"],
                },
            )
            card_count += 1

        for spec in BIBLE_GOLF_NEGATIVE_CARDS:
            Card.objects.update_or_create(
                deck=bible_golf_deck,
                title=spec["title"],
                created_by=None,
                defaults={
                    "type": Card.TYPE_PENALTY,
                    "card_tone": Card.CARD_TONE_NEGATIVE,
                    "prompt": spec["prompt"],
                    "effect": spec["effect"],
                },
            )
            card_count += 1

        for spec in BADGES:
            Badge.objects.update_or_create(code=spec["code"], defaults=spec)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(decks)} decks, {card_count} cards, {len(BADGES)} badges."
            )
        )
