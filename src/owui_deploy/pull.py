"""Export the server's Tools and Functions into files (valves values are never written)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .client import OpenWebUIClient
from .config import Config, derive_description, derive_name, load_config, default_config
from .normalize import normalize
from .planner import remote_description


@dataclass
class PullResult:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # local file differs; not overwritten without --force
    invalid_ids: list[str] = field(default_factory=list)
    valves_dropped: int = 0
    config_written: Path | None = None
    config_kept: Path | None = None
    # (kind, id, field 'active'|'global', config value, server value); rendered by the CLI
    state_differences: list[tuple[str, str, str, bool, bool]] = field(default_factory=list)


def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_config(url: str | None, entries: dict[str, list[dict]]) -> str:
    """Write a fresh ``owui-deploy.toml`` that reproduces the pulled server state (plan exits 0)."""
    lines = ["[server]", f"url = {_toml_str(url or 'http://localhost:8080')}", "", "[paths]",
             'tools = "tools"', 'functions = "functions"', "", "[defaults]", "active = true", "global = false", ""]
    for section, items in (("tools", entries["tool"]), ("functions", entries["function"])):
        for entry in sorted(items, key=lambda e: e["id"]):
            content = entry.get("content") or ""
            override = {}
            if entry.get("name") != derive_name(entry["id"], content, {}):
                override["name"] = _toml_str(entry.get("name") or entry["id"])
            if remote_description(entry) != derive_description(content, {}):
                override["description"] = _toml_str(remote_description(entry))
            if not entry.get("is_active"):
                override["active"] = "false"
            if section == "functions" and entry.get("is_global"):
                override["global"] = "true"
            if override:
                lines.append(f"[{section}.{entry['id']}]")
                lines.extend(f"{k} = {v}" for k, v in override.items())
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def pull(client: OpenWebUIClient, out: Path, config_path: Path, url: str | None, force: bool = False) -> PullResult:
    result = PullResult()
    cfg: Config = load_config(config_path) if config_path.is_file() else default_config(out)
    exported = {kind: client.export_all(kind) for kind in ("tool", "function")}

    for kind, folder in (("tool", cfg.tools_dir), ("function", cfg.functions_dir)):
        for entry in exported[kind]:
            if "valves" in entry:  # a server that ignores "no valves requested": drop, never write
                result.valves_dropped += 1
            item_id = entry["id"]
            if not item_id.isidentifier():
                result.invalid_ids.append(item_id)
                continue
            target = folder / f"{item_id}.py"
            label = f"{kind}:{item_id}"
            content = entry.get("content") or ""
            if target.exists():
                existing = target.read_text(encoding="utf-8")
                if normalize(existing) == content:
                    result.unchanged.append(label)
                    continue
                if not force:
                    result.kept.append(label)
                    continue
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            result.written.append(label)

    if config_path.is_file():
        result.config_kept = config_path
        section = {"tool": "tools", "function": "functions"}
        for kind in ("tool", "function"):
            for entry in exported[kind]:
                override = cfg.overrides[section[kind]].get(entry["id"], {})
                want_active = override.get("active", cfg.default_active)
                if bool(entry.get("is_active")) != want_active:
                    result.state_differences.append((kind, entry["id"], "active", want_active, bool(entry.get("is_active"))))
                if kind == "function":
                    want_global = override.get("global", cfg.default_global)
                    if bool(entry.get("is_global")) != want_global:
                        result.state_differences.append((kind, entry["id"], "global", want_global, bool(entry.get("is_global"))))
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(render_config(url, exported), encoding="utf-8")
        result.config_written = config_path
    return result
