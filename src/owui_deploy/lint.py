"""Static checks for Open WebUI Tools and Functions (OWD001-OWD009).

Nothing is imported or executed: files are only read as text and parsed with ``ast``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import parse_frontmatter
from .normalize import REPLACEMENTS

FUNCTION_CLASSES = ("Pipe", "Filter", "Action", "Event")  # server picks in this order
VALVES_CLASSES = ("Valves", "UserValves")
_SECRET_NAME = re.compile(r"(key|token|secret|passw(or)?d|passwd)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """One lint result. ``msg_key`` indexes the locale tables."""

    path: str
    line: int
    col: int
    code: str
    level: str  # "error" | "warning"
    msg_key: str
    params: dict = field(default_factory=dict)


def _top_level_names(tree: ast.Module) -> dict[str, ast.AST]:
    """Names bound at module level (class, import, assignment) - what ``hasattr(module, X)`` sees."""
    names: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names[node.name] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names[(alias.asname or alias.name).split(".")[0]] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = node
    return names


def _derives_basemodel(cls: ast.ClassDef, classes: dict[str, ast.ClassDef], seen: set[str]) -> bool | None:
    """True if it derives BaseModel, False if it certainly does not, None if unknown (imported base)."""
    if not cls.bases:
        return False
    unknown = False
    for base in cls.bases:
        if isinstance(base, ast.Name):
            if base.id == "BaseModel":
                return True
            if base.id == "object":
                continue
            local = classes.get(base.id)
            if local is not None and base.id not in seen:
                verdict = _derives_basemodel(local, classes, seen | {base.id})
                if verdict:
                    return True
                if verdict is None:
                    unknown = True
            else:
                unknown = True
        elif isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True
        else:
            unknown = True
    return None if unknown else False


def _all_params(args: ast.arguments) -> list[ast.arg]:
    return [*args.posonlyargs, *args.args, *args.kwonlyargs]


def _default_string(value: ast.expr | None) -> str | None:
    """The string default of ``x: str = "v"`` or ``x: str = Field(default="v")``."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    if isinstance(value, ast.Call):
        for kw in value.keywords:
            if kw.arg == "default":
                return _default_string(kw.value)
        if value.args:
            return _default_string(value.args[0])
    return None


def lint_source(path: str, kind: str, source: str, file_stem: str | None = None) -> list[Finding]:
    """Check one file. ``kind`` is ``"tools"`` or ``"functions"``."""
    findings: list[Finding] = []
    stem = file_stem if file_stem is not None else Path(path).stem

    def add(line: int, col: int, code: str, level: str, key: str | None = None, **params: object) -> None:
        findings.append(Finding(path, line, col, code, level, key or f"lint.{code}", dict(params)))

    # OWD004 - file name becomes the id
    if not stem.isidentifier():
        add(1, 1, "OWD004", "error", name=stem)
    elif stem != stem.lower():
        add(1, 1, "OWD004", "warning", "lint.OWD004.case", name=stem, lowered=stem.lower())

    # OWD005 - frontmatter (text based, works even if the code does not parse)
    manifest = parse_frontmatter(source)
    first = source.splitlines()[0].strip() if source.splitlines() else ""
    if first != '"""':
        add(1, 1, "OWD005", "warning", "lint.OWD005.first_line")
    else:
        missing = [k for k in ("title", "version") if not manifest.get(k)]
        if missing:
            add(1, 1, "OWD005", "warning", "lint.OWD005.missing", keys=", ".join(missing))

    # OWD007 - server-side string replacement of imports (text based, same rule as the server)
    for number, text in enumerate(source.splitlines(), start=1):
        for old, new in REPLACEMENTS:
            index = text.find(old)
            if index < 0:
                continue
            following = text[index + len(old) : index + len(old) + 1]
            weird = bool(following) and (following.isalnum() or following == "_")
            add(
                number,
                index + 1,
                "OWD007",
                "warning",
                "lint.OWD007.weird" if weird else "lint.OWD007",
                old=old,
                new=new,
            )

    # OWD001 - syntax
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        add(exc.lineno or 1, exc.offset or 1, "OWD001", "error", detail=exc.msg)
        return sorted(findings, key=lambda f: (f.line, f.col, f.code))

    names = _top_level_names(tree)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    main_class: ast.ClassDef | None = None

    # OWD002 / OWD003 - required classes
    if kind == "tools":
        if "Tools" not in names:
            add(1, 1, "OWD002", "error", "lint.OWD002.tools")
        else:
            main_class = classes.get("Tools")
    else:
        present = [name for name in FUNCTION_CLASSES if name in names]
        if not present:
            add(1, 1, "OWD002", "error", "lint.OWD002.functions")
        else:
            main_class = classes.get(present[0])
            if len(present) > 1:
                node = names[present[0]]
                add(
                    getattr(node, "lineno", 1),
                    1,
                    "OWD003",
                    "warning",
                    chosen=present[0],
                    ignored=", ".join(present[1:]),
                )

    if main_class is not None:
        for member in main_class.body:
            # OWD006 - Valves / UserValves must be pydantic models
            if isinstance(member, ast.ClassDef) and member.name in VALVES_CLASSES:
                if _derives_basemodel(member, classes, {member.name}) is False:
                    add(member.lineno, member.col_offset + 1, "OWD006", "error", name=member.name)
                # OWD009 - suspicious hard-coded secret defaults
                if member.name == "Valves":
                    for field_node in member.body:
                        if isinstance(field_node, ast.AnnAssign) and isinstance(field_node.target, ast.Name):
                            default = _default_string(field_node.value)
                            if default and _SECRET_NAME.search(field_node.target.id):
                                add(field_node.lineno, field_node.col_offset + 1, "OWD009", "warning", name=field_node.target.id)
            # OWD008 - Tool method quality (the model sees docstring and type hints as the spec)
            if kind == "tools" and isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if member.name.startswith("_"):
                    continue
                if not ast.get_docstring(member):
                    add(member.lineno, member.col_offset + 1, "OWD008", "warning", "lint.OWD008.doc", name=member.name)
                untyped = [
                    a.arg
                    for a in _all_params(member.args)
                    if a.arg != "self" and not (a.arg.startswith("__") and a.arg.endswith("__")) and a.annotation is None
                ]
                if untyped or member.returns is None:
                    add(
                        member.lineno,
                        member.col_offset + 1,
                        "OWD008",
                        "warning",
                        "lint.OWD008.hints",
                        name=member.name,
                        missing=", ".join(untyped + ([] if member.returns is not None else ["return"])),
                    )

    return sorted(findings, key=lambda f: (f.line, f.col, f.code))


def detect_kind(path: Path, source: str) -> str:
    """Infer tools/functions for a single file from its parent folder or its content."""
    parent = path.resolve().parent.name
    if parent in ("tools", "functions"):
        return parent
    return "tools" if re.search(r"^class\s+Tools\b", source, re.MULTILINE) else "functions"


def lint_file(path: Path, kind: str, display: str | None = None) -> list[Finding]:
    """Read ``path`` as UTF-8 text and lint it (never imports it)."""
    source = path.read_text(encoding="utf-8", errors="replace")
    return lint_source(display or str(path), kind, source, file_stem=path.stem)


def collect_files(root: Path) -> list[tuple[Path, str, str]]:
    """Return ``(file, kind, display path)`` for a folder or a single file."""
    if root.is_file():
        kind = detect_kind(root, root.read_text(encoding="utf-8", errors="replace"))
        return [(root, kind, root.name)]
    result: list[tuple[Path, str, str]] = []
    subdirs = [(name, root / name) for name in ("tools", "functions") if (root / name).is_dir()]
    if not subdirs and root.name in ("tools", "functions"):
        subdirs = [(root.name, root)]
    for kind, folder in subdirs:
        for file in sorted(folder.glob("*.py")):
            if file.name.startswith("__"):
                continue
            display = file.relative_to(root).as_posix() if folder != root else file.name
            result.append((file, kind, display))
    return result


def lint_path(root: Path) -> tuple[list[Finding], int]:
    """Lint everything under ``root``; return findings and the number of files checked."""
    files = collect_files(root)
    findings: list[Finding] = []
    for file, kind, display in files:
        findings.extend(lint_file(file, kind, display))
    return findings, len(files)
