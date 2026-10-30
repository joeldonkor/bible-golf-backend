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
    # -- Move forward -------------------------------------------------------
    {"title": "Regional Convention", "type": "reward", "prompt": "I went for the regional convention.", "effect": {"move": 1}},
    {"title": "Supported Someone Through Trial", "type": "reward", "prompt": "I supported someone through a trial.", "effect": {"move": 1}},
    {"title": "Love My Partner", "type": "reward", "prompt": "I love my partner with all their flaws.", "effect": {"move": 1}},
    {"title": "Spiritual Goals", "type": "reward", "prompt": "I need to update my spiritual goals.", "effect": {"move": 1}},
    {"title": "Comment at Meeting", "type": "reward", "prompt": "I gave a comment at a meeting.", "effect": {"move": 2}},
    {"title": "Prepared Food for Circuit Overseer", "type": "reward", "prompt": "I prepared food for the Circuit Overseer.", "effect": {"move": 1}},
    {"title": "Personal Studies", "type": "reward", "prompt": "I had my personal studies.", "effect": {"move": 2}},
    {"title": "Applied Bible Principles", "type": "reward", "prompt": "I applied Bible principles.", "effect": {"move": 2}},
    {"title": "Follow God", "type": "reward", "prompt": "Follow God. Move forward 2 spaces.", "effect": {"move": 2}},
    {"title": "Went for the Memorial", "type": "reward", "prompt": "I went for the Memorial.", "effect": {"move": 4}},
    {"title": "Prayed for the Governing Body", "type": "reward", "prompt": "I prayed for the governing body.", "effect": {"move": 1}},
    {"title": "Noticed the Broadcasting", "type": "reward", "prompt": "I noticed the broadcasting.", "effect": {"move": 1}},
    {"title": "Texted a Brother/Sister", "type": "reward", "prompt": "I sent a text to a brother/sister who couldn't attend the meeting.", "effect": {"move": 1}},
    {"title": "Jehovah Is My Father", "type": "reward", "prompt": "Jehovah is my father.", "effect": {"move": 1}},
    {"title": "Shared Scripture with a Friend", "type": "reward", "prompt": "I shared a scripture with a friend.", "effect": {"move": 1}},
    {"title": "Memorial Date", "type": "reward", "prompt": "I can't wait for the next great Memorial. Name the date and move forward 5 spaces.", "effect": {"move": 5}},
    {"title": "Comments at Meetings", "type": "reward", "prompt": "I give comments at meetings.", "effect": {"move": 2}},
    {"title": "Found and Felt Jehovah's Help", "type": "reward", "prompt": "I found and felt Jehovah's help.", "effect": {"move": 1}},
    {"title": "I Love Jehovah", "type": "reward", "prompt": "I love Jehovah.", "effect": {"move": 3}},
    {"title": "Advocate for Principles", "type": "reward", "prompt": "I will advocate for principles or duty.", "effect": {"move": 1}},
    # -- Skip next obstacle -------------------------------------------------
    {"title": "Immunity Card", "type": "reward", "prompt": "Immunity Card! Skip the next three obstacles.", "effect": {"skip_obstacle": 3}},
    {"title": "Love Brothers from the Heart", "type": "reward", "prompt": "I love my brothers from the heart.", "effect": {"skip_obstacle": 1}},
    {"title": "Auxiliary Pioneering", "type": "reward", "prompt": "I applied for auxiliary pioneering.", "effect": {"skip_obstacle": 1}},
    {"title": "Started a Bible Study", "type": "reward", "prompt": "I started a Bible study.", "effect": {"skip_obstacle": 1}},
    {"title": "Prayed for the Congregation", "type": "reward", "prompt": "I prayed for the congregation yesterday.", "effect": {"skip_obstacle": 1}},
    {"title": "I Have a Bible", "type": "reward", "prompt": "I have a Bible.", "effect": {"skip_obstacle": 1}},
    {"title": "Love the Ministry", "type": "reward", "prompt": "I love the Ministry.", "effect": {"skip_obstacle": 1}},
    # -- Interactive challenges (self-report, player hi-5s or states fact) ---
    {"title": "Go to the Elder", "type": "challenge", "prompt": "I need help. Go to the elder.", "effect": {"move": 0}},
    {"title": "Baptism Date", "type": "challenge", "prompt": "I can't forget the day I got baptized. State the date.", "effect": {"move": 0}},
    {"title": "Prayer for All Brothers and Sisters", "type": "challenge", "prompt": "I pray for brothers and sisters worldwide. How many are there? Take a hi-5.", "effect": {"move": 0}},
    {"title": "Faithful Service to Jehovah", "type": "challenge", "prompt": "I have served Jehovah faithfully. How long have you served Jehovah?", "effect": {"move": 0}},
    {"title": "Treasure My Relationship with Jehovah", "type": "challenge", "prompt": "I treasure my relationship with Jehovah. Take a hi-5.", "effect": {"move": 0}},
    {"title": "Prayed for the Elders", "type": "challenge", "prompt": "I prayed for the elders. Take a hi-5.", "effect": {"move": 0}},
    {"title": "Watched the Broadcasting", "type": "challenge", "prompt": "I have watched the broadcasting for the month. Make a reference.", "effect": {"move": 0}},
    {"title": "Love Reading the Watchtower", "type": "challenge", "prompt": "I love reading the Watchtower. What's the cover picture on the Watchtower study edition?", "effect": {"move": 0}},
    {"title": "Know the Circuit Overseer", "type": "challenge", "prompt": "I know the name of our Circuit Overseer. Who is it?", "effect": {"move": 0}},
    {"title": "Know the Bible Theme", "type": "challenge", "prompt": "I know the summary/theme of the Bible. Cite it.", "effect": {"move": 0}},
    {"title": "Prayed for a Brother/Sister", "type": "challenge", "prompt": "I prayed for a brother/sister. Take a hi-5.", "effect": {"move": 0}},
    {"title": "I'm Deeply Sorry", "type": "challenge", "prompt": "I'm deeply sorry, I won't do it again.", "effect": {"move": 0}},
    {"title": "Know Who Wrote Job", "type": "challenge", "prompt": "I know who wrote the book of Job.", "effect": {"move": 0}},
    {"title": "Know the Yeartext", "type": "challenge", "prompt": "I know the yeartext. Cite it.", "effect": {"move": 0}},
    {"title": "Like the Organisation", "type": "challenge", "prompt": "I like the Organisation. Say why.", "effect": {"move": 0}},
    {"title": "Historical Fact About the Organisation", "type": "challenge", "prompt": "I really know the Organisation. Give any historical fact about the Organisation.", "effect": {"move": 0}},
    {"title": "Faithful During Difficult Time", "type": "challenge", "prompt": "I stayed faithful during a difficult time. Take a hi-5 and say why.", "effect": {"move": 0}},
    {"title": "Love Brothers and Sisters", "type": "challenge", "prompt": "I love my brothers and sisters. Say why.", "effect": {"move": 0}},
    {"title": "Love Kingdom Songs", "type": "challenge", "prompt": "I love the Kingdom songs. How many songs are in the current song book?", "effect": {"move": 0}},
    {"title": "Did the Clay Test", "type": "challenge", "prompt": "I did the clay test. Cite it.", "effect": {"move": 0}},
    {"title": "Ready for the Convention", "type": "challenge", "prompt": "I'm ready for the Convention. What's the theme?", "effect": {"move": 0}},
    {"title": "What I Like About My Elders", "type": "challenge", "prompt": "What do you like about your elders? Say one thing.", "effect": {"move": 0}},
    {"title": "Prayed for the Governing Body Challenge", "type": "challenge", "prompt": "I prayed for the governing body. Name any two members and take a hi-5.", "effect": {"move": 0}},
    {"title": "Ready for the 3-Day Convention", "type": "challenge", "prompt": "I am ready for the 3-day Convention. What's the date?", "effect": {"move": 0}},
    {"title": "Bold in Witnessing", "type": "challenge", "prompt": "I was bold in witnessing this year. Tell the story.", "effect": {"move": 0}},
    {"title": "Will Marry Someone Who Loves Jehovah", "type": "challenge", "prompt": "I will marry someone who loves Jehovah. Take a hi-5.", "effect": {"move": 0}},
    {"title": "Volunteered at Kingdom Hall", "type": "challenge", "prompt": "I volunteered at Kingdom Hall to clean up.", "effect": {"move": 0}},
    {"title": "Know Your Group Overseer", "type": "challenge", "prompt": "I know my group overseer. How long have you known them?", "effect": {"move": 0}},
]

BIBLE_GOLF_NEGATIVE_CARDS = [
    # -- Move back (severe) -------------------------------------------------
    {"title": "This Is Not the Truth", "type": "penalty", "prompt": "This is not the truth. Apostate!", "effect": {"move": -6}},
    {"title": "Full Apostate", "type": "penalty", "prompt": "Full Apostate! You have completely rejected the truth.", "effect": {"move": -6}},
    {"title": "Committed Adultery", "type": "penalty", "prompt": "I committed adultery.", "effect": {"move": -4}},
    {"title": "Jehovah Will Forgive Me Anyway", "type": "penalty", "prompt": "Oh, lemme watch once — Jehovah will forgive me.", "effect": {"move": -4}},
    {"title": "Intentionally Sinned", "type": "penalty", "prompt": "I intentionally sinned.", "effect": {"move": -3}},
    {"title": "Tempted for Sex", "type": "penalty", "prompt": "I was tempted for sex. Quote a scripture.", "effect": {"move": -3}},
    {"title": "Leaving for Greener Pastures", "type": "penalty", "prompt": "I'm leaving my partner to look for greener pastures abroad.", "effect": {"move": -3}},
    {"title": "Sex with an Unbeliever", "type": "penalty", "prompt": "Having sex with an unbeliever is the safest.", "effect": {"move": -3}},
    # -- Move back (moderate) -----------------------------------------------
    {"title": "Playing the Betting Game", "type": "penalty", "prompt": "I played the betting game.", "effect": {"move": -2}},
    {"title": "Having Bad Thoughts", "type": "penalty", "prompt": "I'm having bad thoughts.", "effect": {"move": -2}},
    {"title": "Visited a Spiritualist", "type": "penalty", "prompt": "I visited a spiritualist for health.", "effect": {"move": -2}},
    {"title": "Doubting the Truth", "type": "penalty", "prompt": "You should stop — Jehovah's Witnesses are not the truth.", "effect": {"move": -2}},
    {"title": "Stopped Pioneering", "type": "penalty", "prompt": "I want to stop pioneering.", "effect": {"move": -2}},
    {"title": "Leave the Organisation", "type": "penalty", "prompt": "I would leave Jehovah's organisation.", "effect": {"move": -2}},
    {"title": "Peer Pressure", "type": "penalty", "prompt": "I faced peer pressure. Name two Biblical characters that resisted pressure.", "effect": {"move": -2}},
    # -- Move back (minor) --------------------------------------------------
    {"title": "Can't Forgive", "type": "penalty", "prompt": "I can't forgive what he/she did to me.", "effect": {"move": -1}},
    {"title": "Gave in to Masturbation", "type": "penalty", "prompt": "I gave in to masturbation.", "effect": {"move": -1}},
    {"title": "Dating an Unbeliever", "type": "penalty", "prompt": "I am dating an unbeliever.", "effect": {"move": -1}},
    {"title": "Gossip", "type": "penalty", "prompt": "I talk about others behind their back.", "effect": {"move": -1}},
    {"title": "Worldly Entertainment", "type": "penalty", "prompt": "I like going to worldly parties and gatherings.", "effect": {"move": -1}},
    {"title": "Cannot Attend Meetings", "type": "penalty", "prompt": "I cannot attend the meetings.", "effect": {"move": -1}},
    {"title": "Don't Want to Pray", "type": "penalty", "prompt": "I don't want to pray anymore.", "effect": {"move": -1}},
    {"title": "Too Tired to Study", "type": "penalty", "prompt": "I felt too tired to study.", "effect": {"move": -1}},
    {"title": "Hate Meetings", "type": "penalty", "prompt": "I hate going to meetings.", "effect": {"move": -1}},
    {"title": "JW Not Right", "type": "penalty", "prompt": "I would never say Jehovah's Witnesses are right.", "effect": {"move": -1}},
    # -- Interactive challenges (self-report, seek help) --------------------
    {"title": "Faced Ridicule", "type": "challenge", "prompt": "I faced ridicule and nearly lost faith.", "effect": {"move": 0}},
    {"title": "Feelings for an Unbeliever", "type": "challenge", "prompt": "I have feelings for an unbeliever. Cite a scripture.", "effect": {"move": 0}},
    {"title": "Argued with Parents", "type": "challenge", "prompt": "I argued with my parents.", "effect": {"move": 0}},
    {"title": "Discouraged", "type": "challenge", "prompt": "I am discouraged. Seek for help.", "effect": {"move": 0}},
    {"title": "Texting at Meetings", "type": "challenge", "prompt": "I text at meetings.", "effect": {"move": 0}},
    {"title": "Don't Pay Attention at Meetings", "type": "challenge", "prompt": "I don't really pay attention at meetings. Seek help.", "effect": {"move": 0}},
    {"title": "No Longer a Witness", "type": "challenge", "prompt": "I'm no more one of Jehovah's witnesses. Seek help.", "effect": {"move": 0}},
    {"title": "Following Heart Desire", "type": "challenge", "prompt": "I will follow my heart desire.", "effect": {"move": 0}},
    {"title": "Jehovah Doesn't Care", "type": "challenge", "prompt": "Hmm, Jehovah doesn't care. Seek help.", "effect": {"move": 0}},
    {"title": "Rich in This World", "type": "challenge", "prompt": "I have to be rich in this world. Seek help.", "effect": {"move": 0}},
    {"title": "Couldn't Help It", "type": "challenge", "prompt": "I knew it but I couldn't help it.", "effect": {"move": 0}},
    {"title": "Worldly Friends", "type": "challenge", "prompt": "All my friends are from a non-Jehovah household. I can't help it.", "effect": {"move": 0}},
    {"title": "Moving Internationally", "type": "challenge", "prompt": "I am going to move internationally, away from my congregation.", "effect": {"move": 0}},
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
                    "type": spec.get("type", Card.TYPE_REWARD),
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
                    "type": spec.get("type", Card.TYPE_PENALTY),
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
