from django.urls import path

from . import api_views

urlpatterns = [
    path('register/', api_views.RegisterAPIView.as_view(), name='api-register'),
    path('login/', api_views.LoginAPIView.as_view(), name='api-login'),
    path('logout/', api_views.LogoutAPIView.as_view(), name='api-logout'),
    path('profile/', api_views.ProfileAPIView.as_view(), name='api-profile'),
]
