"""
REST surface for tables and live game state.

Every mutating route delegates to `services.py`, which is also what the
websocket consumer calls -- so the HTTP API is a complete fallback for a client
whose socket is down, and the two can't drift apart.
"""

import logging

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.common.pagination import TimelinePagination

from . import services
from .models import GameSession
from .serializers import (
    CreateSessionSerializer,
    GameEventSerializer,
    GameStateSerializer,
    JoinSessionSerializer,
    ResolveCardSerializer,
    SessionSerializer,
)

logger = logging.getLogger(__name__)


class SessionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """`/api/sessions/` -- tables the caller is seated at, and the live board."""

    serializer_class = SessionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            # Schema generation instantiates the view without a real user.
            return GameSession.objects.none()
        # Scoping the queryset (rather than checking inside each handler) means
        # a table you aren't seated at is a 404 on every route here by default.
        return (
            GameSession.objects.with_related()
            .filter(players__user=self.request.user)
            .distinct()
            .order_by("-created_at")
        )

    def get_throttles(self):
        self.throttle_scope = {
            "create": "write",
            "join": "join",
            "roll": "turn",
            "resolve_card": "turn",
            "skip_turn": "turn",
        }.get(self.action)
        return super().get_throttles()

    # ------------------------------------------------------------------ lobby

    @extend_schema(request=CreateSessionSerializer, responses={201: SessionSerializer})
    def create(self, request):
        serializer = CreateSessionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        session = services.create_session(
            user=request.user,
            name=serializer.validated_data["name"],
            deck=serializer.deck,
            max_players=serializer.validated_data.get("max_players", 4),
        )
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                SessionSerializer, description="The session, or `null` if none."
            )
        }
    )
    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request):
        """
        The caller's round in progress, or `null`.

        `null` is a legitimate answer here, not an error -- it's what the Home
        screen uses to decide whether to show the "Continue" card at all.
        """
        session = services.active_session_for(request.user)
        if session is None:
            # DRF renders `Response(None)` as an empty body, which axios hands
            # the client as `""` rather than `null`. The client's type here is
            # `Session | null`, so send a literal JSON null.
            return HttpResponse(b"null", content_type="application/json")
        return Response(SessionSerializer(session).data)

    @extend_schema(request=JoinSessionSerializer, responses={200: SessionSerializer})
    @action(detail=False, methods=["post"], url_path="join")
    def join(self, request):
        serializer = JoinSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.join_session(
            user=request.user, code=serializer.validated_data["code"]
        )
        return Response(SessionSerializer(session).data)

    @extend_schema(request=None, responses={200: GameStateSerializer})
    @action(detail=True, methods=["post"], url_path="start")
    def start(self, request, pk=None):
        self.get_object()  # 404s unless the caller is seated here
        session = services.start_session(user=request.user, session_id=pk)
        return Response(GameStateSerializer(session).data)

    @extend_schema(request=None, responses={204: OpenApiResponse(description="Left")})
    @action(detail=True, methods=["post"], url_path="leave")
    def leave(self, request, pk=None):
        self.get_object()
        services.leave_session(user=request.user, session_id=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------- play

    @extend_schema(responses={200: GameStateSerializer})
    @action(detail=True, methods=["get"], url_path="state")
    def state(self, request, pk=None):
        """
        The live board.

        Clients with a websocket open get this pushed instead; this route is the
        cold-start read and the fallback when the socket is unavailable.
        """
        return Response(GameStateSerializer(self.get_object()).data)

    @extend_schema(request=None, responses={200: GameStateSerializer})
    @action(detail=True, methods=["post"], url_path="roll")
    def roll(self, request, pk=None):
        self.get_object()
        session = services.take_swing(user=request.user, session_id=pk)
        return Response(GameStateSerializer(session).data)

    @extend_schema(request=ResolveCardSerializer, responses={200: GameStateSerializer})
    @action(detail=True, methods=["post"], url_path="resolve-card")
    def resolve_card(self, request, pk=None):
        self.get_object()
        serializer = ResolveCardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.resolve_card(
            user=request.user,
            session_id=pk,
            choice_index=serializer.validated_data.get("choice_index"),
        )
        return Response(GameStateSerializer(session).data)

    @extend_schema(request=None, responses={200: GameStateSerializer})
    @action(detail=True, methods=["post"], url_path="skip-turn")
    def skip_turn(self, request, pk=None):
        """Move past a player whose turn clock has run out."""
        self.get_object()
        session = services.skip_turn(user=request.user, session_id=pk)
        return Response(GameStateSerializer(session).data)

    @extend_schema(responses={200: GameEventSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="events")
    def events(self, request, pk=None):
        """Replay log -- what a client missed while its socket was down."""
        session = self.get_object()
        queryset = session.events.all().order_by("-sequence")
        paginator = TimelinePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(GameEventSerializer(page, many=True).data)
