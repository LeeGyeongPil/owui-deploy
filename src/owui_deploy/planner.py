"""Compare the desired state (local files) with the remote state (export)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .config import DesiredItem, Skipped
from .normalize import normalize


@dataclass
class Change:
    """One line of the plan.

    ``action``: create | update | state | delete | unmanaged | skip.
    """

    kind: str
    id: str
    action: str
    fields: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)
    diff: str = ""


@dataclass
class Plan:
    changes: list[Change]

    @property
    def summary(self) -> dict[str, int]:
        counts = {"create": 0, "update": 0, "state": 0, "delete": 0, "unmanaged": 0, "skipped": 0}
        for change in self.changes:
            counts["skipped" if change.action == "skip" else change.action] += 1
        return counts

    @property
    def writes(self) -> list[Change]:
        """Changes that would send write requests."""
        return [c for c in self.changes if c.action in ("create", "update", "state", "delete")]

    def has_drift(self, fail_on_unmanaged: bool = False) -> bool:
        counts = self.summary
        drift = counts["create"] + counts["update"] + counts["state"] + counts["delete"] + counts["skipped"]
        if fail_on_unmanaged:
            drift += counts["unmanaged"]
        return drift > 0


def remote_description(entry: dict) -> str:
    meta = entry.get("meta") or {}
    return meta.get("description") or ""


def make_diff(item_id: str, remote: str, desired: str) -> str:
    lines = difflib.unified_diff(
        remote.splitlines(keepends=True),
        desired.splitlines(keepends=True),
        fromfile=f"server/{item_id}.py",
        tofile=f"local/{item_id}.py",
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def build_plan(
    desired: list[DesiredItem],
    skipped: list[Skipped],
    remote: dict[str, list[dict]],
    prune: bool = False,
) -> Plan:
    """``remote`` maps ``"tool"``/``"function"`` to the export lists."""
    changes: list[Change] = []
    remote_by_key = {(kind, e["id"]): e for kind, entries in remote.items() for e in entries}
    desired_keys = {(d.kind, d.id) for d in desired}

    for item in desired:
        entry = remote_by_key.get((item.kind, item.id))
        want = normalize(item.content)
        if entry is None:
            fields = ["content", "name", "description"]
            # a new Function starts inactive and non-global; a new Tool starts active
            start_active = item.kind == "tool"
            if item.active != start_active:
                fields.append("active")
            if item.kind == "function" and item.is_global:
                fields.append("global")
            changes.append(Change(item.kind, item.id, "create", fields))
            continue

        update_fields = []
        if entry.get("content") != want:
            update_fields.append("content")
        if entry.get("name") != item.name:
            update_fields.append("name")
        if remote_description(entry) != item.description:
            update_fields.append("description")
        if update_fields:
            change = Change(item.kind, item.id, "update", update_fields)
            if "content" in update_fields:
                change.diff = make_diff(item.id, entry.get("content") or "", want)
            changes.append(change)

        state_fields = []
        detail: dict = {}
        if bool(entry.get("is_active")) != item.active:
            state_fields.append("active")
            detail["active"] = [bool(entry.get("is_active")), item.active]
        if item.kind == "function" and bool(entry.get("is_global")) != item.is_global:
            state_fields.append("global")
            detail["global"] = [bool(entry.get("is_global")), item.is_global]
        if state_fields:
            changes.append(Change(item.kind, item.id, "state", state_fields, detail))

    for (kind, item_id), entry in sorted(remote_by_key.items()):
        if (kind, item_id) not in desired_keys:
            changes.append(Change(kind, item_id, "delete" if prune else "unmanaged"))

    for skip in skipped:
        changes.append(Change(skip.kind, skip.path.stem, "skip", [], {"reason_key": skip.reason_key, "params": skip.params}))

    order = {"create": 0, "update": 1, "state": 2, "delete": 3, "unmanaged": 4, "skip": 5}
    changes.sort(key=lambda c: (order[c.action], c.kind, c.id))
    return Plan(changes)
