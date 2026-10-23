from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.index, name='index'),
    path('bookings/', views.bookings, name='bookings'),
    path('bookings/export.csv', views.bookings_export, name='bookings_export'),
    path('bookings/<str:reference>/', views.booking_detail, name='booking_detail'),
    path('bookings/<str:reference>/status/', views.booking_status, name='booking_status'),
    path('bookings/<str:reference>/payment-status/', views.payment_status, name='payment_status'),
    path('users/', views.users, name='users'),
    path('users/<int:pk>/active/', views.user_active, name='user_active'),
    path('users/<int:pk>/role/', views.user_role, name='user_role'),
]
