from django.contrib import admin

from .models import Card, Deck


class CardInline(admin.TabularInline):
    model = Card
    extra = 0
    fields = ("title", "type", "rarity", "reference", "is_active")
    show_change_link = True


@admin.register(Deck)
class DeckAdmin(admin.ModelAdmin):
    list_display = ("name", "is_custom", "owner", "updated_at")
    list_filter = ("is_custom",)
    search_fields = ("name", "owner__email")
    raw_id_fields = ("owner",)
    inlines = (CardInline,)


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("title", "deck", "type", "rarity", "is_active")
    list_filter = ("type", "rarity", "is_active")
    search_fields = ("title", "prompt", "reference")
    raw_id_fields = ("deck", "created_by")
