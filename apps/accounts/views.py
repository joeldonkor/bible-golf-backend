"""Authentication endpoints: register, login, refresh, me, logout."""

import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from .serializers import (
    AuthSessionSerializer,
    LoginSerializer,
    ProfileUpdateSerializer,
    RegisterSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


class RegisterView(GenericAPIView):
    """`POST /api/auth/register/` -> `AuthSession`."""

    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer
    throttle_scope = "register"

    @extend_schema(responses={201: AuthSessionSerializer})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        logger.info("user_registered", extra={"user_id": str(user.id)})
        body = AuthSessionSerializer(AuthSessionSerializer.for_user(user)).data
        return Response(body, status=status.HTTP_201_CREATED)


class LoginView(GenericAPIView):
    """`POST /api/auth/login/` -> `AuthSession`."""

    permission_classes = (AllowAny,)
    serializer_class = LoginSerializer
    throttle_scope = "auth"

    @extend_schema(responses={200: AuthSessionSerializer})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        body = AuthSessionSerializer(AuthSessionSerializer.for_user(user)).data
        return Response(body)


class RefreshView(TokenRefreshView):
    """
    `POST /api/auth/refresh/` -> `{ access }`.

    Rotation is off, so the client keeps one refresh token for the life of the
    session and this returns only a fresh access token.
    """

    throttle_scope = "auth"


class MeView(GenericAPIView):
    """`GET /api/auth/me/` (session restore) and `PATCH` for profile edits."""

    permission_classes = (IsAuthenticated,)
    serializer_class = UserSerializer

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=ProfileUpdateSerializer, responses={200: UserSerializer})
    def patch(self, request):
        serializer = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data)


class LogoutView(GenericAPIView):
    """
    `POST /api/auth/logout/` -> 204.

    The client posts this with only a bearer token, so every outstanding refresh
    token for the user is blacklisted -- signing out really does end the session
    on every device rather than leaving a valid refresh token in the wild.
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = None

    @extend_schema(request=None, responses={204: OpenApiResponse(description="Signed out")})
    def post(self, request):
        revoked = 0
        for token in OutstandingToken.objects.filter(user=request.user).iterator():
            try:
                RefreshToken(token.token).blacklist()
                revoked += 1
            except TokenError:
                # Already expired or already blacklisted -- nothing to do.
                continue
        logger.info(
            "user_logged_out",
            extra={"user_id": str(request.user.id), "revoked": revoked},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
