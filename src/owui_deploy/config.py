"""Configuration file (``owui-deploy.toml``) and the desired state built from it."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .frontmatter import parse_frontmatter
from .i18n import t

DEFAULT_CONFIG_NAME = "owui-deploy.toml"
KINDS = ("tool", "function")
_TOP_KEYS = {"server", "paths", "defaults", "tools", "functions"}
_ITEM_KEYS = {"tools": {"name", "description", "active"}, "functions": {"name", "description", "active", "global"}}


@dataclass
class Config:
    """Parsed configuration. Paths are absolute (relative to the config file)."""

    path: Path | None
    base_dir: Path
    url: str | None = None
    tools_dir: Path = Path("tools")
    functions_dir: Path = Path("functions")
    default_active: bool = True
    default_global: bool = False
    explicit_paths: set[str] = field(default_factory=set)  # "tools"/"functions" keys set in [paths]
    overrides: dict[str, dict[str, dict]] = field(default_factory=lambda: {"tools": {}, "functions": {}})


@dataclass(frozen=True)
class DesiredItem:
    """What one local file should look like on the server."""

    kind: str  # "tool" | "function"
    id: str
    path: Path
    content: str
    name: str
    description: str
    active: bool
    is_global: bool  # always False for tools


@dataclass(frozen=True)
class Skipped:
    """A local file that cannot become a server item (bad id, id collision)."""

    kind: str
    path: Path
    reason_key: str
    params: dict


def _check_table(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(t("config.not_table", where=where))
    return value


def load_config(path: Path) -> Config:
    """Read and validate the TOML file; raise ConfigError with a fix hint on any problem."""
    if not path.is_file():
        raise ConfigError(t("config.missing", path=str(path)))
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(t("config.invalid_toml", path=str(path), detail=str(exc))) from exc

    unknown = sorted(set(data) - _TOP_KEYS)
    if unknown:
        raise ConfigError(t("config.unknown_key", where=str(path), keys=", ".join(unknown)))

    base = path.resolve().parent
    cfg = Config(path=path, base_dir=base)
    cfg.tools_dir = base / "tools"
    cfg.functions_dir = base / "functions"

    server = _check_table(data.get("server", {}), "[server]")
    if "url" in server:
        if not isinstance(server["url"], str):
            raise ConfigError(t("config.bad_type", where="server.url", expected="string"))
        cfg.url = server["url"]

    paths = _check_table(data.get("paths", {}), "[paths]")
    for key, attr in (("tools", "tools_dir"), ("functions", "functions_dir")):
        if key in paths:
            if not isinstance(paths[key], str):
                raise ConfigError(t("config.bad_type", where=f"paths.{key}", expected="string"))
            setattr(cfg, attr, (base / paths[key]))
            cfg.explicit_paths.add(key)

    defaults = _check_table(data.get("defaults", {}), "[defaults]")
    for key, attr in (("active", "default_active"), ("global", "default_global")):
        if key in defaults:
            if not isinstance(defaults[key], bool):
                raise ConfigError(t("config.bad_type", where=f"defaults.{key}", expected="true/false"))
            setattr(cfg, attr, defaults[key])

    for section in ("tools", "functions"):
        table = _check_table(data.get(section, {}), f"[{section}]")
        for item_id, values in table.items():
            values = _check_table(values, f"[{section}.{item_id}]")
            bad = sorted(set(values) - _ITEM_KEYS[section])
            if bad:
                raise ConfigError(t("config.unknown_key", where=f"[{section}.{item_id}]", keys=", ".join(bad)))
            for key, value in values.items():
                expected = str if key in ("name", "description") else bool
                if not isinstance(value, expected):
                    kind_text = "string" if expected is str else "true/false"
                    raise ConfigError(t("config.bad_type", where=f"{section}.{item_id}.{key}", expected=kind_text))
            cfg.overrides[section][item_id] = dict(values)
    return cfg


def default_config(base_dir: Path) -> Config:
    """Configuration used when no file exists (``lint`` on a bare folder, ``pull`` into a new one)."""
    return Config(path=None, base_dir=base_dir, tools_dir=base_dir / "tools", functions_dir=base_dir / "functions")


def derive_name(item_id: str, content: str, override: dict) -> str:
    """name: config > frontmatter title > id."""
    return override.get("name") or parse_frontmatter(content).get("title") or item_id


def derive_description(content: str, override: dict) -> str:
    """description: config > frontmatter description > empty."""
    return override.get("description") if "description" in override else parse_frontmatter(content).get("description", "")


def build_desired(cfg: Config) -> tuple[list[DesiredItem], list[Skipped]]:
    """Read the local folders and return the desired items and the files that must be skipped."""
    items: list[DesiredItem] = []
    skipped: list[Skipped] = []
    for kind, section, folder in (("tool", "tools", cfg.tools_dir), ("function", "functions", cfg.functions_dir)):
        seen: dict[str, Path] = {}
        if not folder.is_dir():
            if section in cfg.explicit_paths:  # a configured folder that does not exist is most likely a typo
                skipped.append(Skipped(kind, folder, "skip.folder_missing", {"folder": str(folder)}))
        for file in sorted(folder.glob("*.py") if folder.is_dir() else []):
            if file.name.startswith("__"):
                continue
            stem = file.stem
            if not stem.isidentifier():
                skipped.append(Skipped(kind, file, "skip.bad_id", {"name": stem}))
                continue
            item_id = stem.lower()  # the server lowercases ids
            if item_id in seen:
                skipped.append(Skipped(kind, file, "skip.duplicate", {"id": item_id, "other": seen[item_id].name}))
                continue
            seen[item_id] = file
            try:
                content = file.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ConfigError(t("config.not_utf8", path=str(file))) from exc
            override = cfg.overrides[section].get(item_id, {})
            items.append(
                DesiredItem(
                    kind=kind,
                    id=item_id,
                    path=file,
                    content=content,
                    name=derive_name(item_id, content, override),
                    description=derive_description(content, override),
                    active=override.get("active", cfg.default_active),
                    is_global=False if kind == "tool" else override.get("global", cfg.default_global),
                )
            )
        stale = set(cfg.overrides[section]) - set(seen)
        for item_id in sorted(stale):
            skipped.append(Skipped(kind, folder / f"{item_id}.py", "skip.config_without_file", {"id": item_id}))
    return items, skipped
