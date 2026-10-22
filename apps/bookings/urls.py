from django.urls import path

from . import views

app_name = 'bookings'

urlpatterns = [
    path('', views.history, name='history'),
    path('book/<int:slot_pk>/', views.book_slot, name='book'),
    path('<str:reference>/', views.detail, name='detail'),
    path('<str:reference>/cancel/', views.cancel, name='cancel'),
]
