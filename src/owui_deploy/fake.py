"""A small practice mock of Open WebUI 0.13.3 (NOT a real Open WebUI).

It models the behaviours that matter for deploying Tools and Functions, each one
recorded from a real 0.13.3 instance (see ``tests/fixtures/owui-0.13.3``):

* the import rewrite on save (``from utils`` -> ``from open_webui.utils``)
* toggles flip the current value (they do not set it)
* a new Function is created inactive and non-global; a new Tool is active
* a file without a Pipe/Filter/Action/Event (Tools: ``Tools``) is answered with the
  one-line 400 ``[ERROR: Error creating function]``
* bad id / duplicate id are 400
* ``POST /functions/sync`` deletes every Function that is not in the list
* ``export?include_valves=true`` returns valves in plain text

Difference from the real server: the code is never executed. Classes are detected with ``ast``.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path
from urllib.parse import unquote

import httpx

from .frontmatter import parse_frontmatter
from .normalize import normalize

FUNCTION_CLASSES = ("Pipe", "Filter", "Action", "Event")
FAKE_VERSION = "0.13.3"
_NOW = 1794477106  # fixed clock keeps the mock deterministic

# Response key sets per (kind, operation), copied from the recorded 0.13.3 responses.
_BASE_FUNCTION = ["version_id", "id", "user_id", "type", "name", "meta", "is_active", "is_global", "updated_at", "created_at"]
_BASE_TOOL = ["version_id", "id", "user_id", "name", "meta", "is_active", "access_grants", "updated_at", "created_at"]
KEYS = {
    ("function", "list"): _BASE_FUNCTION,
    ("function", "create"): _BASE_FUNCTION,
    ("function", "get"): [*_BASE_FUNCTION, "content"],
    ("function", "toggle"): [*_BASE_FUNCTION, "content"],
    ("function", "update"): [*_BASE_FUNCTION, "content"],
    ("function", "export"): [*_BASE_FUNCTION, "content"],
    ("function", "export_valves"): [*_BASE_FUNCTION, "content", "valves"],
    ("function", "sync"): [*_BASE_FUNCTION, "content", "valves"],
    ("tool", "list"): _BASE_TOOL,
    ("tool", "create"): _BASE_TOOL,
    ("tool", "toggle"): _BASE_TOOL,
    ("tool", "get"): [*_BASE_TOOL, "content", "specs", "user", "write_access"],
    ("tool", "update"): [*_BASE_TOOL, "content", "specs"],
    ("tool", "export"): [*_BASE_TOOL, "content", "specs"],
}

# Seed used by ``--fake`` when no state file exists yet. Sources are created through the
# normal create path, so the import rewrite etc. apply to them as on a real server.
SEED_TOOL_CLOCK = '''"""
title: Clock
version: 0.1.0
"""
from datetime import datetime


class Tools:
    def now(self) -> str:
        """Return the current time."""
        return datetime.now().isoformat()
'''

SEED_PII_MASK = '''"""
title: PII Mask
version: 0.1.0
description: Mask e-mail addresses before the model sees them
"""
import re

from pydantic import BaseModel
from utils.misc import get_last_user_message


class Filter:
    class Valves(BaseModel):
        api_key: str = ""
        priority: int = 0

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        message = get_last_user_message(body["messages"])
        if message:
            body["messages"][-1]["content"] = re.sub(r"[\\w.]+@[\\w.]+", "[email]", message)
        return body
'''

SEED_LEGACY_FILTER = '''"""
title: Legacy Filter
version: 0.0.1
"""


class Filter:
    def inlet(self, body: dict) -> dict:
        return body
'''


class FakeOpenWebUI:
    """In-memory (optionally JSON-persisted) server model with an httpx MockTransport adapter."""

    def __init__(self, state_path: Path | None = None, token: str | None = None) -> None:
        self.state_path = state_path
        self.token = token  # None = accept any bearer token
        self.log: list[tuple[str, str]] = []
        self.bodies: list[tuple[str, str, dict]] = []  # JSON bodies of write requests (for tests)
        self.items: dict[str, dict[str, dict]] = {"tool": {}, "function": {}}
        self.valves: dict[str, dict] = {}
        self.history: list[dict] = []
        if state_path is not None and state_path.is_file():
            self._load()
        else:
            self._seed()

    # -- persistence -------------------------------------------------------------------------
    def _load(self) -> None:
        assert self.state_path is not None
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.items = data["items"]
        self.valves = data.get("valves", {})
        self.history = data.get("history", [])

    def save(self) -> None:
        if self.state_path is None:
            return
        payload = {"items": self.items, "valves": self.valves, "history": self.history}
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def _seed(self) -> None:
        self._create("tool", {"id": "clock", "name": "Clock", "content": SEED_TOOL_CLOCK, "meta": {"description": "Clock"}})
        function = self._create(
            "function",
            {"id": "pii_mask", "name": "PII Mask", "content": SEED_PII_MASK, "meta": {"description": "Mask e-mail addresses before the model sees them"}},
        )
        self.valves["pii_mask"] = {"api_key": "dummy-not-secret", "priority": 3}
        assert function["is_active"] is False
        self._create("function", {"id": "legacy_filter", "name": "Legacy Filter", "content": SEED_LEGACY_FILTER, "meta": {"description": ""}})
        self.items["function"]["legacy_filter"]["is_active"] = True
        self.log.clear()

    # -- transport ---------------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def writes(self) -> list[tuple[str, str]]:
        """Logged write requests (everything except GET)."""
        return [entry for entry in self.log if entry[0] != "GET"]

    # -- domain helpers ----------------------------------------------------------------------
    @staticmethod
    def _detect_type(kind: str, content: str) -> str | None:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return None
        names = set()
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".")[0] for a in node.names)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        if kind == "tool":
            return "tool" if "Tools" in names else None
        for candidate in FUNCTION_CLASSES:
            if candidate in names:
                return candidate.lower()
        return None

    @staticmethod
    def _specs(content: str) -> list[dict]:
        specs: list[dict] = []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return specs
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Tools":
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not member.name.startswith("_"):
                        specs.append(
                            {
                                "name": member.name,
                                "description": ast.get_docstring(member) or "",
                                "parameters": {"properties": {}, "type": "object"},
                            }
                        )
        return specs

    def _new_record(self, kind: str, form: dict, content: str, ftype: str | None) -> dict:
        meta_in = form.get("meta") or {}
        manifest = parse_frontmatter(content)
        record = {
            "version_id": str(uuid.uuid4()),
            "id": form["id"],
            "user_id": "REDACTED-user-id",
            "name": form.get("name", form["id"]),
            "content": content,
            "created_at": _NOW,
            "updated_at": _NOW,
        }
        if kind == "tool":
            record.update(
                is_active=True,
                access_grants=[],
                meta={"i18n": None, "description": meta_in.get("description", ""), "manifest": manifest, "has_user_valves": False},
            )
        else:
            record.update(
                type=ftype,
                is_active=False,
                is_global=False,
                meta={"description": meta_in.get("description", ""), "manifest": manifest, "toggle": False},
            )
        return record

    def _create(self, kind: str, form: dict) -> dict:
        item_id = form.get("id", "")
        if not isinstance(item_id, str) or not item_id.isidentifier():
            raise _Reject(400, "Only alphanumeric characters and underscores are allowed in the id")
        item_id = item_id.lower()
        form = {**form, "id": item_id}
        if item_id in self.items[kind]:
            raise _Reject(400, "Uh-oh! This id is already registered. Please choose another id string.")
        content = normalize(form.get("content", ""))
        ftype = self._detect_type(kind, content)
        if ftype is None:
            raise _Reject(400, f"[ERROR: Error creating {kind}]")
        record = self._new_record(kind, form, content, ftype)
        self.items[kind][item_id] = record
        self._add_history(kind, item_id, form.get("commit_message"))
        return record

    def _update(self, kind: str, item_id: str, form: dict) -> dict:
        record = self.items[kind].get(item_id)
        if record is None:
            raise _Reject(404, "Not found")
        content = normalize(form.get("content", ""))
        ftype = self._detect_type(kind, content)
        if ftype is None:
            raise _Reject(400, f"[ERROR: Error updating {kind}]")
        record["content"] = content
        record["name"] = form.get("name", record["name"])
        record["meta"]["description"] = (form.get("meta") or {}).get("description", "")
        record["meta"]["manifest"] = parse_frontmatter(content)
        if kind == "function":
            record["type"] = ftype
        record["version_id"] = str(uuid.uuid4())
        self._add_history(kind, item_id, form.get("commit_message"))
        return record

    def _add_history(self, kind: str, item_id: str, message: str | None) -> None:
        self.history.append({"kind": kind, "id": item_id, "commit_message": message})

    def _shape(self, kind: str, op: str, record: dict) -> dict:
        full = dict(record)
        full.setdefault("specs", self._specs(record["content"]) if kind == "tool" else None)
        full.setdefault("user", None)
        full.setdefault("write_access", True)
        full["valves"] = self.valves.get(record["id"], {})
        return {key: full[key] for key in KEYS[(kind, op)] if key in full}

    # -- HTTP --------------------------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.log.append((request.method, path))
        if request.method != "GET" and request.content:
            self.bodies.append((request.method, path, json.loads(request.content)))
        if self.token is not None and request.headers.get("authorization") != f"Bearer {self.token}":
            return _json(401, {"detail": "Not authenticated"})
        try:
            response = self._route(request.method, path, request)
            if request.method != "GET":
                self.save()
            return response
        except _Reject as exc:
            return _json(exc.status, {"detail": exc.detail})

    def _route(self, method: str, path: str, request: httpx.Request) -> httpx.Response:
        if method == "GET" and path == "/api/version":
            return _json(200, {"version": FAKE_VERSION})
        parts = [unquote(p) for p in path.strip("/").split("/")]
        if len(parts) < 3 or parts[:2] != ["api", "v1"] or parts[2] not in ("tools", "functions"):
            return _json(404, {"detail": "Not Found"})
        kind = "tool" if parts[2] == "tools" else "function"
        rest = parts[3:]
        body = json.loads(request.content) if request.content else {}

        if method == "GET" and rest == []:
            return _json(200, [self._shape(kind, "list", r) for r in self.items[kind].values()])
        if method == "GET" and rest == ["export"]:
            with_valves = kind == "function" and request.url.params.get("include_valves") == "true"
            op = "export_valves" if with_valves else "export"
            return _json(200, [self._shape(kind, op, r) for r in self.items[kind].values()])
        if method == "POST" and rest == ["create"]:
            return _json(200, self._shape(kind, "create", self._create(kind, body)))
        if method == "POST" and rest == ["sync"] and kind == "function":
            keep = {f["id"] for f in body.get("functions", [])}
            for item_id in list(self.items["function"]):
                if item_id not in keep:
                    del self.items["function"][item_id]
            for form in body.get("functions", []):
                if form["id"] in self.items["function"]:
                    self._update("function", form["id"], form)
                else:
                    self._create("function", form)
            return _json(200, [self._shape("function", "sync", r) for r in self.items["function"].values()])
        if len(rest) >= 2 and rest[0] == "id":
            item_id = rest[1]
            action = rest[2:]
            record = self.items[kind].get(item_id)
            if record is None:
                return _json(404, {"detail": "Not found"})
            if method == "GET" and action == []:
                return _json(200, self._shape(kind, "get", record))
            if method == "POST" and action == ["update"]:
                return _json(200, self._shape(kind, "update", self._update(kind, item_id, body)))
            if method == "POST" and action == ["toggle"]:
                record["is_active"] = not record["is_active"]
                return _json(200, self._shape(kind, "toggle", record))
            if method == "POST" and action == ["toggle", "global"] and kind == "function":
                record["is_global"] = not record["is_global"]
                return _json(200, self._shape(kind, "toggle", record))
            if method == "DELETE" and action == ["delete"]:
                del self.items[kind][item_id]
                self.valves.pop(item_id, None)
                return _json(200, True)
            if action in (["valves"], ["valves", "update"]):
                if method == "POST":
                    self.valves[item_id] = body
                return _json(200, self.valves.get(item_id, {}))
        return _json(404, {"detail": "Not Found"})


class _Reject(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _json(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body)
