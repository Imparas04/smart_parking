from rest_framework.routers import DefaultRouter

from . import api_views

router = DefaultRouter()
router.register('locations', api_views.LocationViewSet, basename='api-location')
router.register('slots', api_views.SlotViewSet, basename='api-slot')

urlpatterns = router.urls
