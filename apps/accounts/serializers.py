"""Serializers for the client's `User`, `AuthSession` and auth requests."""

from django.contrib.auth import authenticate, password_validation
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """Mirrors `src/types/auth.ts#User` once camelised by the renderer."""

    level = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(source="date_joined", read_only=True)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "display_name",
            "avatar_url",
            "role",
            "level",
            "xp",
            "created_at",
        )
        read_only_fields = fields

    def get_avatar_url(self, obj: User) -> str | None:
        # The client's type is `string | null`; empty strings would render as a
        # broken image instead of the initials fallback.
        return obj.avatar_url or None


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)


class AuthSessionSerializer(serializers.Serializer):
    """`{ user, tokens }` -- the body `login` and `register` return."""

    user = UserSerializer(read_only=True)
    tokens = TokenPairSerializer(read_only=True)

    @staticmethod
    def for_user(user: User) -> dict:
        refresh = RefreshToken.for_user(user)
        return {
            "user": user,
            "tokens": {"access": str(refresh.access_token), "refresh": str(refresh)},
        }


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"].lower().strip(),
            password=attrs["password"],
        )
        if user is None:
            # One message for "no such account" and "wrong password" so the
            # endpoint can't be used to enumerate registered emails.
            raise serializers.ValidationError(
                {"detail": "Incorrect email or password."}, code="invalid_credentials"
            )
        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "This account has been deactivated."}, code="inactive"
            )
        attrs["user"] = user
        return attrs


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    # Bounds match the client's zod schema so the two agree on what's valid.
    display_name = serializers.CharField(min_length=2, max_length=40)
    password = serializers.CharField(
        write_only=True, min_length=6, max_length=72, trim_whitespace=False
    )

    def validate_email(self, value: str) -> str:
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("That email is already registered.")
        return value

    def validate_password(self, value: str) -> str:
        password_validation.validate_password(value)
        return value

    @transaction.atomic
    def create(self, validated_data) -> User:
        return User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            display_name=validated_data["display_name"].strip(),
        )


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """The handful of fields a player may change about themselves."""

    class Meta:
        model = User
        fields = ("display_name", "avatar_url", "title")
        extra_kwargs = {
            "display_name": {"min_length": 2, "max_length": 40},
            "avatar_url": {"required": False, "allow_blank": True},
            "title": {"required": False, "allow_blank": True},
        }
