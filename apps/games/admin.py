from django.contrib import admin

from .models import GameEvent, GameSession, Player


class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0
    fields = ("user", "turn_order", "position", "score", "is_host", "connection_count")
    readonly_fields = ("user",)


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "status", "stage", "turn_number", "created_at")
    list_filter = ("status", "stage")
    search_fields = ("code", "name", "host__email")
    readonly_fields = ("id", "code", "version", "created_at", "updated_at")
    inlines = (PlayerInline,)
    # Sessions carry several FKs to large tables; raw ids keep the page fast.
    raw_id_fields = ("host", "deck", "active_player", "pending_card", "winner")


@admin.register(GameEvent)
class GameEventAdmin(admin.ModelAdmin):
    list_display = ("session", "sequence", "type", "created_at")
    list_filter = ("type",)
    search_fields = ("session__code",)
    raw_id_fields = ("session", "actor")
    readonly_fields = ("session", "sequence", "type", "actor", "payload", "created_at")
