from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('api/auth/', include('apps.accounts.api_urls')),
    path('parking/', include('apps.parking.urls')),
    path('api/parking/', include('apps.parking.api_urls')),
    path('bookings/', include('apps.bookings.urls')),
    path('api/bookings/', include('apps.bookings.api_urls')),
    path('payments/', include('apps.payments.urls')),
    path('api/payments/', include('apps.payments.api_urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('', include('apps.core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
