from django.contrib import admin

from .models import FeatureChat, FeatureChatTurn, FoundItem, ItemImage, LostItem


@admin.register(ItemImage)
class ItemImageAdmin(admin.ModelAdmin):
    list_display = ('id', 'uploader', 'is_blurred', 'created_at')


@admin.register(LostItem)
class LostItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'item_name', 'category', 'user', 'place', 'status', 'created_at')
    list_filter = ('status', 'category')
    exclude = ('text_embedding', 'image_embedding')


@admin.register(FoundItem)
class FoundItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'item_name', 'category', 'finder', 'place', 'status', 'created_at')
    list_filter = ('status', 'category')
    exclude = ('text_embedding', 'image_embedding')


admin.site.register(FeatureChat)
admin.site.register(FeatureChatTurn)
