from rest_framework.routers import SimpleRouter

from . import api_views

router = SimpleRouter()
router.register('locations', api_views.LocationViewSet, basename='api-location')
router.register('slots', api_views.SlotViewSet, basename='api-slot')

urlpatterns = router.urls
