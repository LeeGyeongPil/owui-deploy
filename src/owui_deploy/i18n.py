"""Language selection and message lookup (English / Korean).

Priority: ``--lang`` > ``OWUI_DEPLOY_LANG`` > ``LC_ALL`` > ``LC_MESSAGES`` > ``LANG``.
Anything that does not start with ``ko`` falls back to English.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Mapping

SUPPORTED = ("en", "ko")
_current = "en"


def _normalize(value: str | None) -> str | None:
    if not value:
        return None
    return "ko" if value.strip().lower().startswith("ko") else "en"


def resolve_lang(cli_value: str | None, env: Mapping[str, str]) -> str:
    """Pick the output language following the documented priority."""
    for candidate in (
        cli_value,
        env.get("OWUI_DEPLOY_LANG"),
        env.get("LC_ALL"),
        env.get("LC_MESSAGES"),
        env.get("LANG"),
    ):
        picked = _normalize(candidate)
        if picked:
            return picked
    return "en"


def set_lang(lang: str) -> None:
    global _current
    _current = lang if lang in SUPPORTED else "en"


def get_lang() -> str:
    return _current


@lru_cache(maxsize=None)
def load_catalog(lang: str) -> dict[str, str]:
    """Load ``locales/<lang>.json`` (the message table, one place for all text)."""
    path = resources.files("owui_deploy") / "locales" / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def t(key: str, **params: object) -> str:
    """Translate ``key`` into the current language (falls back to English, then the key)."""
    text = load_catalog(_current).get(key)
    if text is None:
        text = load_catalog("en").get(key, key)
    return text.format(**params) if params else text
