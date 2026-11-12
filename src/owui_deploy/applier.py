"""Run a plan against a server: create/update, toggle only when needed, delete only on request."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .client import OpenWebUIClient
from .config import DesiredItem
from .errors import ApiError
from .planner import Plan


@dataclass
class Rejection:
    kind: str
    id: str
    action: str
    status: int
    detail: str


@dataclass
class ApplyResult:
    done: list[tuple[str, str, str]] = field(default_factory=list)  # (action, kind, id)
    rejected: list[Rejection] = field(default_factory=list)


def git_short_hash(directory: Path) -> str | None:
    """Short hash of HEAD in ``directory``, or None when git or a repository is missing."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _ensure_state(client: OpenWebUIClient, item: DesiredItem, result: ApplyResult) -> None:
    """Re-read the item and toggle only what differs (the toggle API flips, it does not set)."""
    current = client.get(item.kind, item.id)
    if bool(current.get("is_active")) != item.active:
        client.toggle(item.kind, item.id)
        result.done.append(("toggle", item.kind, item.id))
    if item.kind == "function" and bool(current.get("is_global")) != item.is_global:
        client.toggle_global(item.id)
        result.done.append(("toggle_global", item.kind, item.id))


def apply_plan(
    client: OpenWebUIClient,
    plan: Plan,
    desired: list[DesiredItem],
    message: str | None = None,
) -> ApplyResult:
    """Apply create/update/state/delete entries. One rejected item does not stop the others."""
    by_key = {(d.kind, d.id): d for d in desired}
    result = ApplyResult()
    for change in plan.changes:
        if change.action not in ("create", "update", "state", "delete"):
            continue
        item = by_key.get((change.kind, change.id))
        try:
            if change.action == "delete":
                client.delete(change.kind, change.id)
                result.done.append(("delete", change.kind, change.id))
                continue
            assert item is not None  # create/update/state always come from a desired item
            payload = {
                "id": item.id,
                "name": item.name,
                "content": item.content,
                "meta": {"description": item.description},
            }
            if change.action == "create":
                client.create(item.kind, payload)
                result.done.append(("create", item.kind, item.id))
                _ensure_state(client, item, result)
            elif change.action == "update":
                if message:
                    payload["commit_message"] = message
                client.update(item.kind, item.id, payload)
                result.done.append(("update", item.kind, item.id))
            else:
                _ensure_state(client, item, result)
        except ApiError as exc:
            result.rejected.append(Rejection(change.kind, change.id, change.action, exc.status, exc.detail))
    return result
