from django.urls import path

from . import api_views

urlpatterns = [path('summary/', api_views.SummaryAPIView.as_view(), name='api-dashboard-summary')]
