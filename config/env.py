"""Tiny .env loader (no extra dependency). Real environment variables always win."""
import os
from pathlib import Path


def load_env_file(path, environ=None):
    environ = os.environ if environ is None else environ
    path = Path(path)
    if not path.is_file():
        return 0
    loaded = 0
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[7:]
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if key and key not in environ:
            environ[key] = value
            loaded += 1
    return loaded
