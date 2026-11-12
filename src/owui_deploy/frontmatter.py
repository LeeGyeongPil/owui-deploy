"""Frontmatter parser with the same rules as Open WebUI 0.13.3 (`utils/plugin.py`)."""

from __future__ import annotations

import re

_PATTERN = re.compile(r"^\s*([a-z_]+):\s*(.*)\s*$", re.IGNORECASE)


def parse_frontmatter(content: str) -> dict[str, str]:
    """Return the ``key: value`` pairs of the leading docstring.

    The first line must be ``\"\"\"`` (surrounding spaces allowed); otherwise the
    result is empty, exactly like the server. Parsing stops at the first line
    that contains ``\"\"\"``.
    """
    lines = content.splitlines()
    if len(lines) < 1 or lines[0].strip() != '"""':
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if '"""' in line:
            break
        match = _PATTERN.match(line)
        if match:
            key, value = match.groups()
            result[key.strip()] = value.strip()
    return result
