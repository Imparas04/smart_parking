from rest_framework.routers import SimpleRouter

from . import api_views

router = SimpleRouter()
router.register('vehicles', api_views.VehicleViewSet, basename='api-vehicle')
router.register('', api_views.BookingViewSet, basename='api-booking')  # keep last: '' also matches 'vehicles'

urlpatterns = router.urls
