"""Small persistent preferences (settings.json in the user data folder)."""

import json

from .paths import data_dir

_PATH = data_dir() / "settings.json"


def load():
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**changes):
    data = load()
    data.update(changes)
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_PATH)
    except OSError:
        pass  # preferences are a convenience; never fail over them
