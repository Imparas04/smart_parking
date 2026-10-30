from django import template
from django.utils.html import format_html

register = template.Library()

SLOT_ICONS = {'car': 'car', 'bike': 'bike', 'ev': 'bolt', 'accessible': 'access'}


@register.simple_tag
def icon(name, css=''):
    """Inline SVG icon from the sprite in partials/icons.html: {% icon 'car' %}."""
    return format_html('<svg class="icon {}" aria-hidden="true" focusable="false"><use href="#i-{}"/></svg>', css, name)


@register.filter
def slot_icon(slot_type):
    return SLOT_ICONS.get(slot_type, 'car')


@register.filter
def pct(value, total):
    """value as a whole-number percentage of total (0 when total is 0)."""
    try:
        value, total = int(value), int(total)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, round(100 * value / total))) if total > 0 else 0


@register.filter
def meter_class(available, total):
    """CSS state for an availability bar: '' (plenty), 'low' (20% or less free) or 'none' (full)."""
    try:
        available, total = int(available), int(total)
    except (TypeError, ValueError):
        return 'none'
    if total <= 0 or available <= 0:
        return 'none'
    return 'low' if available / total <= 0.2 else ''


@register.filter
def art(pk):
    """One of four colour variants for a location card, stable per location."""
    try:
        return int(pk) % 4
    except (TypeError, ValueError):
        return 0
