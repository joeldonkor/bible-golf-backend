"""Leaderboard and badge endpoints."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import BadgeSerializer, LeaderboardEntrySerializer
from .services import SCOPE_GLOBAL, SCOPES, badges_for, rank_of, ranked_users


class LeaderboardView(ListAPIView):
    """
    `GET /api/leaderboard/?scope=friends|congregation|global`.

    The caller's own row is appended when they fall outside the page, which is
    what lets the "PGA board" show a family sitting at rank 142 underneath the
    top five without paging there.
    """

    serializer_class = LeaderboardEntrySerializer

    def scope(self) -> str:
        scope = self.request.query_params.get("scope", SCOPE_GLOBAL)
        return scope if scope in SCOPES else SCOPE_GLOBAL

    def get_queryset(self):
        return ranked_users(user=self.request.user, scope=self.scope())

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "scope",
                str,
                description="friends | congregation | global (default: global)",
            )
        ],
        responses={200: LeaderboardEntrySerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        rows = list(page) if page is not None else list(queryset)

        if request.user.is_active and all(row.id != request.user.id for row in rows):
            own = rank_of(user=request.user, scope=self.scope())
            if own is not None:
                rows.append(own)

        data = self.get_serializer(rows, many=True).data
        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)


class BadgeListView(APIView):
    """`GET /api/leaderboard/badges/` -- every badge, flagged earned or not."""

    @extend_schema(responses={200: BadgeSerializer(many=True)})
    def get(self, request):
        badges = badges_for(request.user)
        data = BadgeSerializer(badges, many=True).data
        # Paginated envelope: the client reads `results` for this route too.
        return Response({"count": len(data), "next": None, "previous": None, "results": data})
