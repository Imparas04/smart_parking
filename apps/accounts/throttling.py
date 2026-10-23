"""Login brute-force protection: temporary lockout per (client IP + username) and per client IP."""
import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger('apps.security')


def client_ip(request):
    """Client address. X-Forwarded-For is only honoured when DJANGO_TRUSTED_PROXY_COUNT > 0,
    and then only the entry added by our own proxy, so clients cannot spoof it."""
    proxies = settings.TRUSTED_PROXY_COUNT
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if proxies and forwarded:
        parts = [p.strip() for p in forwarded.split(',') if p.strip()]
        if parts:
            return parts[-min(proxies, len(parts))]
    return request.META.get('REMOTE_ADDR', 'unknown')


def _keys(request, username):
    ip = client_ip(request)
    return f'loginfail:user:{ip}:{(username or "").strip().lower()[:150]}', f'loginfail:ip:{ip}'


def is_blocked(request, username):
    user_key, ip_key = _keys(request, username)
    return (cache.get(user_key, 0) >= settings.LOGIN_MAX_FAILURES_PER_USER
            or cache.get(ip_key, 0) >= settings.LOGIN_MAX_FAILURES_PER_IP)


def record_failure(request, username):
    for key in _keys(request, username):
        cache.add(key, 0, settings.LOGIN_LOCKOUT_SECONDS)
        try:
            cache.incr(key)
        except ValueError:  # key expired between add and incr
            cache.set(key, 1, settings.LOGIN_LOCKOUT_SECONDS)
    logger.warning('Failed login for %r from %s', (username or '')[:50], client_ip(request))


def reset(request, username):
    cache.delete(_keys(request, username)[0])


def lockout_message():
    return f'Too many failed login attempts. Please try again in {settings.LOGIN_LOCKOUT_SECONDS // 60} minutes.'
