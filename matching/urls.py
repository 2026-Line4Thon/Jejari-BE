from django.urls import path

from .views import DevMatchingRunView

urlpatterns = [
    path('dev/matching/<int:lost_item_id>', DevMatchingRunView.as_view(), name='dev-matching-run'),
]
