"""Exceptions that map to exit code 2 ("tool error") in the CLI."""

from __future__ import annotations


class ToolError(Exception):
    """A problem with the tool setup, not with the user's files (exit code 2)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigError(ToolError):
    """The configuration file is missing or invalid."""


class OwuiConnectionError(ToolError):
    """The server cannot be reached."""


class AuthError(ToolError):
    """The server answered 401 or 403."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class ApiError(Exception):
    """The server rejected one request (HTTP 4xx/5xx other than 401/403).

    This is *not* a ToolError: the apply step collects these per item and keeps going.
    """

    def __init__(self, status: int, detail: str, method: str = "", path: str = "") -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail
        self.method = method
        self.path = path
