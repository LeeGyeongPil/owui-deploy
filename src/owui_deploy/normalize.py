"""Reproduce the server's import rewriting so that plan does not report fake diffs.

Open WebUI 0.13.3 runs a plain ``str.replace`` over the uploaded source before it
stores it (``utils/plugin.py::replace_imports``). The same replacement is applied
to the local file before comparing.
"""

from __future__ import annotations

REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("from utils", "from open_webui.utils"),
    ("from apps", "from open_webui.apps"),
    ("from main", "from open_webui.main"),
    ("from config", "from open_webui.config"),
)


def normalize(content: str) -> str:
    """Apply the server's import rewriting (idempotent)."""
    for old, new in REPLACEMENTS:
        content = content.replace(old, new)
    return content
