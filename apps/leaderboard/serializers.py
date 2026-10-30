"""Serializers for `LeaderboardEntry` and `Badge`."""

from rest_framework import serializers


class LeaderboardEntrySerializer(serializers.Serializer):
    """Mirrors `src/types/leaderboard.ts#LeaderboardEntry`."""

    rank = serializers.IntegerField(read_only=True)
    user_id = serializers.UUIDField(source="id", read_only=True)
    display_name = serializers.CharField(read_only=True)
    avatar_url = serializers.SerializerMethodField()
    points = serializers.IntegerField(read_only=True)
    level = serializers.CharField(read_only=True)
    title = serializers.SerializerMethodField()

    def get_avatar_url(self, obj) -> str | None:
        return obj.avatar_url or None

    def get_title(self, obj) -> str | None:
        return obj.title or None


class BadgeSerializer(serializers.Serializer):
    """Mirrors `src/types/leaderboard.ts#Badge`."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    icon_name = serializers.CharField(read_only=True)
    earned = serializers.BooleanField(read_only=True)
