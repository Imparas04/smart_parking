from rest_framework.routers import SimpleRouter

from . import api_views

router = SimpleRouter()
router.register('', api_views.PaymentViewSet, basename='api-payment')

urlpatterns = router.urls
