"""Thin Open WebUI admin API client (``/api/v1/tools`` and ``/api/v1/functions``)."""

from __future__ import annotations

import httpx

from .errors import ApiError, AuthError, OwuiConnectionError, ToolError
from .i18n import t

_REQUIRED = {"id", "name", "content", "is_active"}


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict) and "detail" in body:
        return str(body["detail"])
    return str(body)[:200]


class OpenWebUIClient:
    """One method per endpoint the tool needs. It never calls ``/functions/sync``."""

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpenWebUIClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low level ---------------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: object) -> object:
        try:
            response = self._http.request(method, path, **kwargs)  # type: ignore[arg-type]
        except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
            raise ToolError(t("err.bad_url", url=self.base_url)) from exc
        except httpx.TransportError as exc:
            raise OwuiConnectionError(t("err.connect", url=self.base_url, detail=str(exc) or type(exc).__name__)) from exc
        if response.status_code in (401, 403):
            raise AuthError(t("err.auth", status=response.status_code, detail=_detail(response)), response.status_code)
        if response.status_code >= 400:
            raise ApiError(response.status_code, _detail(response), method, path)
        try:
            return response.json()
        except ValueError as exc:
            raise ToolError(t("err.not_json", url=self.base_url, path=path)) from exc

    @staticmethod
    def _base(kind: str) -> str:
        return "/api/v1/tools" if kind == "tool" else "/api/v1/functions"

    # -- endpoints ---------------------------------------------------------------------------
    def export_all(self, kind: str) -> list[dict]:
        """Every item of ``kind`` including its source (valves are not requested)."""
        data = self._request("GET", f"{self._base(kind)}/export")
        if not isinstance(data, list):
            raise ToolError(t("err.unexpected", url=self.base_url))
        for entry in data:
            if not isinstance(entry, dict) or not _REQUIRED <= set(entry):
                raise ToolError(t("err.unexpected", url=self.base_url))
        return data

    def get(self, kind: str, item_id: str) -> dict:
        data = self._request("GET", f"{self._base(kind)}/id/{item_id}")
        if not isinstance(data, dict):
            raise ToolError(t("err.unexpected", url=self.base_url))
        return data

    def create(self, kind: str, payload: dict) -> dict:
        return self._request("POST", f"{self._base(kind)}/create", json=payload)  # type: ignore[return-value]

    def update(self, kind: str, item_id: str, payload: dict) -> dict:
        return self._request("POST", f"{self._base(kind)}/id/{item_id}/update", json=payload)  # type: ignore[return-value]

    def toggle(self, kind: str, item_id: str) -> dict:
        return self._request("POST", f"{self._base(kind)}/id/{item_id}/toggle")  # type: ignore[return-value]

    def toggle_global(self, item_id: str) -> dict:
        return self._request("POST", f"/api/v1/functions/id/{item_id}/toggle/global")  # type: ignore[return-value]

    def delete(self, kind: str, item_id: str) -> object:
        return self._request("DELETE", f"{self._base(kind)}/id/{item_id}/delete")
