from django.conf import settings


class SecurityHeadersMiddleware:
    """Adds Content-Security-Policy and Permissions-Policy. Django's own admin is left out of the CSP
    because it still uses a few inline snippets."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith('/admin/'):
            name = 'Content-Security-Policy-Report-Only' if settings.CSP_REPORT_ONLY else 'Content-Security-Policy'
            response.headers.setdefault(name, settings.CSP_POLICY)
        response.headers.setdefault('Permissions-Policy', settings.PERMISSIONS_POLICY)
        return response
