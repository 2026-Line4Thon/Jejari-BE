from django.urls import path

from .views import (
    CandidateDetailView,
    CandidateRejectView,
    DevMatchingRunView,
    LostItemCandidateListView,
    OwnershipAnswerView,
    OwnershipCheckCreateView,
    OwnershipCheckDetailView,
)

urlpatterns = [
    path('items/lost/<int:item_id>/candidates', LostItemCandidateListView.as_view(), name='lost-item-candidates'),
    path('candidates/<int:candidate_id>', CandidateDetailView.as_view(), name='candidate-detail'),
    path('candidates/<int:candidate_id>/reject', CandidateRejectView.as_view(), name='candidate-reject'),
    path(
        'candidates/<int:candidate_id>/ownership-checks',
        OwnershipCheckCreateView.as_view(),
        name='ownership-check-create',
    ),
    path('ownership-checks/<int:check_id>', OwnershipCheckDetailView.as_view(), name='ownership-check-detail'),
    path('ownership-checks/<int:check_id>/answers', OwnershipAnswerView.as_view(), name='ownership-check-answers'),
    path('dev/matching/<int:lost_item_id>', DevMatchingRunView.as_view(), name='dev-matching-run'),
]
