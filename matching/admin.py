from django.contrib import admin

from .models import MatchCandidate, OwnershipCheck


@admin.register(MatchCandidate)
class MatchCandidateAdmin(admin.ModelAdmin):
    list_display = ('id', 'lost_item', 'found_item', 'total_score', 'similarity_label', 'status')
    list_filter = ('status', 'similarity_label')


@admin.register(OwnershipCheck)
class OwnershipCheckAdmin(admin.ModelAdmin):
    list_display = ('id', 'candidate', 'result', 'created_at')
