from django.urls import path

from .views import (
    CandidateDetailView,
    CandidateRejectView,
    DevMatchingRunView,
    LostItemCandidateListView,
)

urlpatterns = [
    path('items/lost/<int:item_id>/candidates', LostItemCandidateListView.as_view(), name='lost-item-candidates'),
    path('candidates/<int:candidate_id>', CandidateDetailView.as_view(), name='candidate-detail'),
    path('candidates/<int:candidate_id>/reject', CandidateRejectView.as_view(), name='candidate-reject'),
    path('dev/matching/<int:lost_item_id>', DevMatchingRunView.as_view(), name='dev-matching-run'),
]
