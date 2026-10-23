from django.conf import settings


def site(request):
    return {'SITE_NAME': settings.SITE_NAME, 'TIMEZONE_LABEL': settings.SITE_TIMEZONE_LABEL}
