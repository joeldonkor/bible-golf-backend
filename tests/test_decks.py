"""Deck browsing, card authoring and art handling."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.decks.models import Card, Deck

pytestmark = pytest.mark.django_db


def png_bytes(size=(4, 4)) -> bytes:
    """A real PNG -- the upload endpoint decodes what it is given."""
    buffer = io.BytesIO()
    Image.new("RGB", size, (109, 59, 215)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_built_in_decks_are_visible_to_everyone(auth, host, guest, deck):
    for user in (host, guest):
        names = [d["name"] for d in auth(user).get("/api/decks/").json()["results"]]
        assert "Parables" in names


def test_a_custom_deck_is_private_to_its_owner(auth, host, guest):
    created = auth(host).post("/api/decks/", {"name": "Our Family Verses"}, format="json")
    assert created.status_code == 201
    assert created.json()["isCustom"] is True
    assert created.json()["ownerId"] == str(host.id)

    guest_names = [d["name"] for d in auth(guest).get("/api/decks/").json()["results"]]
    assert "Our Family Verses" not in guest_names


def test_card_count_reflects_the_deck(auth, host, deck):
    listed = auth(host).get("/api/decks/").json()["results"]
    parables = next(d for d in listed if d["name"] == "Parables")
    assert parables["cardCount"] == deck.cards.count()


def test_creating_a_question_card(auth, host, deck):
    response = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "question",
            "title": "Complete the Verse",
            "prompt": "The Lord is my ______.",
            "reference": "Psalm 23:1",
            "options": ["Shepherd", "Rock", "Light"],
            "correctOptionIndex": 0,
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    card = response.json()
    assert card["options"] == ["Shepherd", "Rock", "Light"]
    assert card["correctOptionIndex"] == 0
    # The form doesn't collect an effect, so the server supplies the default.
    assert card["effect"] == {"points": 15}
    assert card["rarity"] == "common"


def test_a_question_without_options_is_rejected(auth, host, deck):
    response = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "question",
            "title": "Unanswerable",
            "prompt": "What comes next?",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "options" in response.json()


def test_options_are_dropped_for_non_questions(auth, host, deck):
    """Only a question is scored against an answer, so the rest carry none."""
    response = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "scripture",
            "title": "Be Still",
            "prompt": "Be still, and know that I am God.",
            "options": ["a", "b"],
            "correctOptionIndex": 1,
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["options"] is None
    assert response.json()["correctOptionIndex"] is None


def test_a_card_added_to_a_built_in_deck_stays_private(auth, host, guest, deck):
    auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "challenge",
            "title": "Our House Rule",
            "prompt": "Name someone you'll pray for this week.",
        },
        format="json",
    )

    host_titles = [
        c["title"] for c in auth(host).get(f"/api/decks/{deck.id}/cards/").json()["results"]
    ]
    guest_titles = [
        c["title"] for c in auth(guest).get(f"/api/decks/{deck.id}/cards/").json()["results"]
    ]
    assert "Our House Rule" in host_titles
    assert "Our House Rule" not in guest_titles


def test_a_local_file_uri_is_refused_with_a_way_forward(auth, host, deck):
    """
    The card creator hands us the picker's `file://` URI.

    Storing it would look like success and then show a broken image on every
    other phone at the table, so it's rejected -- and the message names the
    upload endpoint that does work.
    """
    response = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "scripture",
            "title": "Sunset",
            "prompt": "The heavens declare the glory of God.",
            "artUrl": "file:///var/mobile/Containers/Data/tmp/IMG_0042.jpg",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "uploads/card-art" in response.json()["artUrl"][0]


def test_asset_and_https_art_references_are_accepted(auth, host, deck):
    for reference in ("asset://card-lost-sheep", "https://cdn.example.com/a.jpg"):
        response = auth(host).post(
            "/api/cards/",
            {
                "deckId": str(deck.id),
                "type": "scripture",
                "title": f"Art {reference[:5]}",
                "prompt": "The heavens declare the glory of God.",
                "artUrl": reference,
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert response.json()["artUrl"] == reference


def test_uploading_card_art_returns_a_usable_url(auth, host, deck, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    upload = SimpleUploadedFile("pic.png", png_bytes(), content_type="image/png")

    response = auth(host).post("/api/uploads/card-art/", {"file": upload}, format="multipart")
    assert response.status_code == 201, response.json()
    url = response.json()["url"]
    assert url.startswith("http")

    # And that URL is accepted as card art.
    created = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "scripture",
            "title": "Uploaded",
            "prompt": "The heavens declare the glory of God.",
            "artUrl": url,
        },
        format="json",
    )
    assert created.status_code == 201


def test_a_non_image_upload_is_refused(auth, host, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    upload = SimpleUploadedFile(
        "payload.svg", b"<svg onload=alert(1)>", content_type="image/svg+xml"
    )
    response = auth(host).post("/api/uploads/card-art/", {"file": upload}, format="multipart")
    assert response.status_code == 415


def test_a_disguised_file_is_refused_despite_its_content_type(auth, host, settings, tmp_path):
    """A `Content-Type` header is a claim; the bytes are the evidence."""
    settings.MEDIA_ROOT = tmp_path
    upload = SimpleUploadedFile(
        "notreally.png", b"GIF89a-not-really-a-png-at-all", content_type="image/png"
    )
    response = auth(host).post("/api/uploads/card-art/", {"file": upload}, format="multipart")
    assert response.status_code == 415


def test_an_oversized_upload_is_refused(auth, host, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.MAX_CARD_ART_BYTES = 1024
    big = SimpleUploadedFile(
        "big.png", io.BytesIO(b"0" * 4096).getvalue(), content_type="image/png"
    )
    response = auth(host).post("/api/uploads/card-art/", {"file": big}, format="multipart")
    assert response.status_code == 413


def test_effect_values_are_clamped(auth, host, deck):
    """A crafted card can't teleport its author down the fairway."""
    response = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "reward",
            "title": "Warp Speed",
            "prompt": "Advance!",
            "effect": {"move": 999, "points": 10_000},
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["effect"] == {"move": 6, "points": 100}


def test_unknown_effect_keys_are_rejected(auth, host, deck):
    response = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(deck.id),
            "type": "reward",
            "title": "Sneaky",
            "prompt": "Advance!",
            "effect": {"winGame": True},
        },
        format="json",
    )
    assert response.status_code == 400


def test_a_deck_you_cannot_see_is_not_a_valid_target(auth, host, guest):
    private = Deck.objects.create(name="Theirs", is_custom=True, owner=guest)
    response = auth(host).post(
        "/api/cards/",
        {
            "deckId": str(private.id),
            "type": "scripture",
            "title": "Nope",
            "prompt": "Should not be created.",
        },
        format="json",
    )
    assert response.status_code == 400
    assert Card.objects.filter(deck=private).count() == 0


def test_retiring_a_card_hides_it_without_breaking_history(auth, host, deck):
    created = (
        auth(host)
        .post(
            "/api/cards/",
            {
                "deckId": str(deck.id),
                "type": "challenge",
                "title": "Temporary",
                "prompt": "Share a verse you love.",
            },
            format="json",
        )
        .json()
    )

    assert auth(host).delete(f"/api/cards/{created['id']}/").status_code == 204

    card = Card.objects.get(pk=created["id"])
    assert card.is_active is False  # soft delete: drawn cards stay resolvable
    titles = [
        c["title"] for c in auth(host).get(f"/api/decks/{deck.id}/cards/").json()["results"]
    ]
    assert "Temporary" not in titles


def test_decks_need_authentication(api):
    assert api.get("/api/decks/").status_code == 401
