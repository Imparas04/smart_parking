from rest_framework.exceptions import ValidationError

MAX_ID = 2 ** 63 - 1


def parse_id(value):
    """A positive database id from user input, or None if it is missing, non-numeric or out of range."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= MAX_ID else None


def query_id(params, name):
    """API helper: optional ?name=<id> filter; a bad value is a 400 (never a 500)."""
    raw = params.get(name)
    if raw in (None, ''):
        return None
    value = parse_id(raw)
    if value is None:
        raise ValidationError({name: ['Enter a valid id.']})
    return value


def clean_search(value, limit=100):
    return (value or '').strip()[:limit]
