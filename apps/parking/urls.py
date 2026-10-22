from django.urls import path

from . import views

app_name = 'parking'

urlpatterns = [
    path('', views.location_list, name='location_list'),
    path('<int:pk>/', views.location_detail, name='location_detail'),
    path('slots/<int:pk>/', views.slot_detail, name='slot_detail'),
    path('manage/new/', views.location_create, name='location_create'),
    path('manage/<int:pk>/edit/', views.location_update, name='location_update'),
    path('manage/<int:pk>/delete/', views.location_delete, name='location_delete'),
    path('manage/<int:location_pk>/slots/new/', views.slot_create, name='slot_create'),
    path('manage/<int:location_pk>/slots/bulk/', views.slot_bulk_create, name='slot_bulk_create'),
    path('manage/slots/<int:pk>/edit/', views.slot_update, name='slot_update'),
    path('manage/slots/<int:pk>/delete/', views.slot_delete, name='slot_delete'),
]
