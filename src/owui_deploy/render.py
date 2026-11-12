"""Human readable and JSON output for lint results and plans."""

from __future__ import annotations

import json

from .applier import ApplyResult
from .i18n import t
from .lint import Finding
from .planner import Plan

_SYMBOL = {"create": "+", "update": "~", "state": "~", "delete": "-", "unmanaged": "?", "skip": "!"}


def finding_text(finding: Finding) -> str:
    message = t(finding.msg_key, **finding.params)
    return f"{finding.path}:{finding.line} {finding.code} {finding.level}: {message}"


def lint_summary(findings: list[Finding], files: int) -> str:
    errors = sum(1 for f in findings if f.level == "error")
    warnings = sum(1 for f in findings if f.level == "warning")
    if not findings:
        return t("lint.clean", files=files)
    return t("lint.summary", files=files, errors=errors, warnings=warnings)


def lint_json(findings: list[Finding], files: int) -> str:
    payload = {
        "findings": [
            {
                "path": f.path,
                "line": f.line,
                "col": f.col,
                "code": f.code,
                "level": f.level,
                "message": t(f.msg_key, **f.params),
            }
            for f in findings
        ],
        "summary": {
            "files": files,
            "errors": sum(1 for f in findings if f.level == "error"),
            "warnings": sum(1 for f in findings if f.level == "warning"),
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _field_names(fields: list[str]) -> str:
    return ", ".join(t(f"field.{name}") for name in fields)


def change_line(change, width: int = 0) -> str:  # noqa: ANN001 - planner.Change
    symbol = _SYMBOL[change.action]
    head = f"{symbol} {change.action:<9} {change.kind:<8} {change.id:<{width}}"
    if change.action in ("create", "update"):
        return f"{head}  ({_field_names(change.fields)})"
    if change.action == "state":
        parts = [f"{name}: {str(old).lower()} -> {str(new).lower()}" for name, (old, new) in change.detail.items()]
        return f"{head}  ({', '.join(parts)})"
    if change.action == "unmanaged":
        return f"{head}  ({t('plan.unmanaged_note')})"
    if change.action == "delete":
        return f"{head}  ({t('plan.delete_note')})"
    reason = t(change.detail["reason_key"], **change.detail["params"])
    return f"{head}  ({reason})"


def summary_line(plan: Plan) -> str:
    counts = plan.summary
    parts = [t(f"plan.part.{name}", n=counts[name]) for name in ("create", "update", "state", "delete", "unmanaged", "skipped") if counts[name]]
    if not parts:
        return t("plan.none")
    return t("plan.summary", parts=", ".join(parts))


def plan_text(plan: Plan, show_diff: bool = False) -> str:
    width = max((len(c.id) for c in plan.changes), default=0)
    lines = [change_line(c, width) for c in plan.changes]
    if show_diff:
        for change in plan.changes:
            if change.diff:
                lines.append("")
                lines.append(change.diff.rstrip("\n"))
    if lines:
        lines.append("")
    lines.append(summary_line(plan))
    return "\n".join(lines)


def plan_json(plan: Plan, mock: bool, server: str, show_diff: bool = False) -> str:
    changes = []
    for c in plan.changes:
        entry = {"kind": c.kind, "id": c.id, "action": c.action, "fields": c.fields}
        if c.detail and c.action == "state":
            entry["detail"] = c.detail
        if c.action == "skip":
            entry["detail"] = {"reason": t(c.detail["reason_key"], **c.detail["params"])}
        if show_diff and c.diff:
            entry["diff"] = c.diff
        changes.append(entry)
    payload = {"server": server, "mock": mock, "changes": changes, "summary": plan.summary}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def apply_lines(result: ApplyResult) -> list[str]:
    lines = [t("apply.done_line", action=a, kind=k, id=i) for a, k, i in result.done]
    for r in result.rejected:
        lines.append(t("apply.rejected_line", action=r.action, kind=r.kind, id=r.id, status=r.status, detail=r.detail))
    return lines
