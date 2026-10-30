"""Deck browsing and card authoring."""

import logging
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files.storage import default_storage
from drf_spectacular.utils import extend_schema
from PIL import Image, UnidentifiedImageError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Card, Deck
from .serializers import (
    CardArtResultSerializer,
    CardArtUploadSerializer,
    CardSerializer,
    CreateCardSerializer,
    CreateDeckSerializer,
    DeckSerializer,
)

logger = logging.getLogger(__name__)

# Formats we are willing to store, and the extension each one gets.
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


def _verified_image_format(upload) -> str | None:
    """
    The file's real format, or None if it isn't an image we accept.

    `Image.verify()` parses the file without decoding every pixel, so a
    malformed or hostile file is rejected cheaply rather than being trusted on
    the strength of its Content-Type header.
    """
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    finally:
        upload.seek(0)
    return image_format if image_format in FORMAT_EXTENSIONS else None


class DeckViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    `/api/decks/` and `/api/decks/{id}/`, plus `/api/decks/{id}/cards/`.

    Listing is scoped to what the caller may see: every built-in deck and their
    own custom ones.
    """

    serializer_class = DeckSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Schema generation instantiates the view without a real user.
            return Deck.objects.none()
        return (
            Deck.objects.visible_to(self.request.user)
            .with_card_count()
            .order_by("is_custom", "name")
        )

    def get_serializer_class(self):
        return CreateDeckSerializer if self.action == "create" else DeckSerializer

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "write"
        return super().get_throttles()

    @extend_schema(responses={201: DeckSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deck = serializer.save()
        # Re-read through the list queryset so `cardCount` is present.
        deck = self.get_queryset().get(pk=deck.pk)
        return Response(DeckSerializer(deck).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: CardSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="cards")
    def cards(self, request, pk=None):
        deck = self.get_object()
        queryset = (
            Card.objects.filter(deck=deck)
            .playable()
            .visible_to(request.user)
            .order_by("created_at")
        )
        page = self.paginate_queryset(queryset)
        serializer = CardSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class CardViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """`/api/cards/` -- create a custom card; read or retire your own."""

    serializer_class = CardSerializer
    throttle_scope = "write"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Card.objects.none()
        return Card.objects.playable().visible_to(self.request.user)

    def get_serializer_class(self):
        return CreateCardSerializer if self.action == "create" else CardSerializer

    @extend_schema(responses={201: CardSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = serializer.save()
        logger.info(
            "card_created",
            extra={"card_id": str(card.id), "deck_id": str(card.deck_id)},
        )
        return Response(CardSerializer(card).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance: Card):
        if instance.created_by_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You can only remove cards you created.")
        # Soft delete: sessions that already drew this card keep a valid record.
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class CardArtUploadView(APIView):
    """
    `POST /api/uploads/card-art/` (multipart, field `file`) -> `{ url }`.

    The card creator picks an image from the device, whose `file://` URI means
    nothing to anyone else at the table. Upload it here first and send the
    returned absolute URL as the card's `artUrl`.
    """

    parser_classes = (MultiPartParser, FormParser)
    throttle_scope = "write"
    serializer_class = CardArtUploadSerializer

    @extend_schema(
        request={"multipart/form-data": CardArtUploadSerializer},
        responses={201: CardArtResultSerializer},
    )
    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response(
                {"detail": "Attach the image as the 'file' field.", "code": "no_file"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > settings.MAX_CARD_ART_BYTES:
            limit_mb = settings.MAX_CARD_ART_BYTES // (1024 * 1024)
            return Response(
                {"detail": f"Images must be under {limit_mb}MB.", "code": "too_large"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        # The declared Content-Type is just a claim, so the file is decoded and
        # the real format is what decides -- otherwise anything at all could be
        # stored and served back under an image URL.
        image_format = _verified_image_format(upload)
        if image_format is None:
            return Response(
                {"detail": "Upload a JPEG, PNG or WebP image.", "code": "bad_type"},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        # The client's filename is never trusted: the extension comes from the
        # verified format and the name is one we generate.
        name = str(
            PurePosixPath("card-art")
            / str(request.user.id)
            / f"{uuid.uuid4().hex}{FORMAT_EXTENSIONS[image_format]}"
        )
        stored = default_storage.save(name, upload)
        url = default_storage.url(stored)
        if url.startswith("/") and settings.PUBLIC_BASE_URL:
            url = settings.PUBLIC_BASE_URL + url

        logger.info("card_art_uploaded", extra={"path": stored, "bytes": upload.size})
        return Response({"url": url}, status=status.HTTP_201_CREATED)
