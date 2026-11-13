"""Command line entry point: ``owui-deploy {lint,pull,plan,apply}``.

Exit codes: 0 = nothing to report, 1 = differences or problems found, 2 = tool error.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Sequence

from . import __version__, i18n
from .applier import apply_plan, git_short_hash
from .client import OpenWebUIClient
from .config import DEFAULT_CONFIG_NAME, Config, build_desired, load_config
from .errors import ToolError
from .fake import FakeOpenWebUI
from .i18n import t
from .lint import lint_path, lint_source
from .planner import Plan, build_plan
from .pull import pull as run_pull
from . import render

FAKE_STATE_NAME = ".owui-deploy-fake.json"


# argparse's own fixed phrases come from gettext; map them to Korean so that `--lang ko` is complete.
_ARGPARSE_KO = {
    "usage: ": "사용법: ",
    "positional arguments": "위치 인자",
    "options": "옵션",
    "optional arguments": "옵션",
    "%(prog)s: error: %(message)s\n": "%(prog)s: 오류: %(message)s\n",
    "unrecognized arguments: %s": "인식할 수 없는 인자입니다: %s",
    "the following arguments are required: %s": "다음 인자가 필요합니다: %s",
    "invalid choice: %(value)r (choose from %(choices)s)": "잘못된 선택입니다: %(value)r (선택 가능: %(choices)s)",
    "expected one argument": "값이 하나 필요합니다",
    "show this help message and exit": "도움말을 보여 주고 종료합니다",
}
_ARGPARSE_ORIGINAL = argparse._


def _localize_argparse(lang: str) -> None:
    """Swap argparse's translator for the chosen language (English restores the original)."""
    if lang == "ko":
        argparse._ = lambda text: _ARGPARSE_KO.get(text, _ARGPARSE_ORIGINAL(text))  # type: ignore[attr-defined]
    else:
        argparse._ = _ARGPARSE_ORIGINAL  # type: ignore[attr-defined]


def _preparse_lang(argv: Sequence[str]) -> str | None:
    """Find ``--lang`` before argparse runs, so that the help text itself is translated."""
    for index, arg in enumerate(argv):
        if arg == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def build_parser() -> argparse.ArgumentParser:
    """Build the parser; every help string is looked up in the current language."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--lang", choices=i18n.SUPPORTED, default=argparse.SUPPRESS, help=t("help.lang"))

    server = argparse.ArgumentParser(add_help=False, parents=[common])
    server.add_argument("--config", metavar="PATH", help=t("help.config", name=DEFAULT_CONFIG_NAME))
    server.add_argument("--url", metavar="URL", help=t("help.url"))
    server.add_argument("--fake", action="store_true", help=t("help.fake"))

    parser = argparse.ArgumentParser(
        prog="owui-deploy",
        add_help=False,
        description=t("help.description"),
        epilog=t("help.epilog"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-h", "--help", action="help", help=t("help.help"))
    parser.add_argument("--version", action="version", version=f"owui-deploy {__version__}", help=t("help.version"))
    parser.add_argument("--lang", choices=i18n.SUPPORTED, default=None, help=t("help.lang"))
    sub = parser.add_subparsers(dest="command", metavar="{lint,pull,plan,apply}", required=True)

    def add(name: str, parents: list[argparse.ArgumentParser], help_key: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, parents=parents, add_help=False, help=t(help_key), description=t(help_key))
        p.add_argument("-h", "--help", action="help", help=t("help.help"))
        return p

    p_lint = add("lint", [common, ], "help.lint")
    p_lint.add_argument("--config", metavar="PATH", help=t("help.config", name=DEFAULT_CONFIG_NAME))
    p_lint.add_argument("path", nargs="?", metavar="PATH", help=t("help.lint_path"))
    p_lint.add_argument("--json", action="store_true", help=t("help.json"))
    p_lint.add_argument("--strict", action="store_true", help=t("help.strict"))

    p_plan = add("plan", [server], "help.plan")
    p_plan.add_argument("--diff", action="store_true", help=t("help.diff"))
    p_plan.add_argument("--json", action="store_true", help=t("help.json"))
    p_plan.add_argument("--prune", action="store_true", help=t("help.prune_plan"))
    p_plan.add_argument("--fail-on-unmanaged", action="store_true", help=t("help.fail_on_unmanaged"))

    p_apply = add("apply", [server], "help.apply")
    p_apply.add_argument("--yes", "-y", action="store_true", help=t("help.yes"))
    p_apply.add_argument("--prune", action="store_true", help=t("help.prune_apply"))
    p_apply.add_argument("--message", "-m", metavar="TEXT", help=t("help.message"))

    p_pull = add("pull", [common], "help.pull")
    p_pull.add_argument("--out", metavar="DIR", default=".", help=t("help.out"))
    p_pull.add_argument("--url", metavar="URL", help=t("help.url"))
    p_pull.add_argument("--fake", action="store_true", help=t("help.fake"))
    p_pull.add_argument("--force", action="store_true", help=t("help.force"))
    return parser


# -- helpers ---------------------------------------------------------------------------------
def _load_cfg(args: argparse.Namespace) -> Config:
    path = Path(args.config) if args.config else Path.cwd() / DEFAULT_CONFIG_NAME
    return load_config(path)


def _open_client(args: argparse.Namespace, base_dir: Path, cfg_url: str | None) -> tuple[OpenWebUIClient, str, bool]:
    """Return ``(client, server label, is_mock)``; the mock needs no URL or token."""
    if args.fake:
        state_path = base_dir / FAKE_STATE_NAME
        try:
            shown = state_path.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            shown = state_path
        fake = FakeOpenWebUI(state_path=state_path)
        return OpenWebUIClient("http://fake.invalid", "fake", transport=fake.transport()), f"fake ({shown})", True
    url = args.url or os.environ.get("OWUI_URL") or cfg_url
    if not url:
        raise ToolError(t("err.no_url"))
    token = os.environ.get("OWUI_TOKEN")
    if not token:
        raise ToolError(t("err.no_token"))
    return OpenWebUIClient(url, token), url, False


def _banner(label: str, mock: bool, to_stderr: bool = False) -> None:
    stream = sys.stderr if to_stderr else sys.stdout
    if mock:
        print(t("fake.banner", state=label.removeprefix("fake (").removesuffix(")")), file=stream)
    else:
        print(t("plan.server", url=label), file=stream)


def _remote(client: OpenWebUIClient) -> dict[str, list[dict]]:
    return {kind: client.export_all(kind) for kind in ("tool", "function")}


def _plan(args: argparse.Namespace, prune: bool) -> tuple[Plan, list, OpenWebUIClient, str, bool, Config]:
    cfg = _load_cfg(args)
    desired, skipped = build_desired(cfg)
    client, label, mock = _open_client(args, cfg.base_dir, cfg.url)
    try:
        plan = build_plan(desired, skipped, _remote(client), prune=prune)
    except BaseException:
        client.close()  # do not leak the connection when the server cannot be read
        raise
    return plan, desired, client, label, mock, cfg


# -- commands --------------------------------------------------------------------------------
def cmd_lint(args: argparse.Namespace) -> int:
    if args.path:
        root = Path(args.path)
    else:
        config_path = Path(args.config) if args.config else Path.cwd() / DEFAULT_CONFIG_NAME
        root = Path.cwd()
        if args.config or config_path.is_file():
            cfg = load_config(config_path)
            return _lint_config(cfg, args)
    if not root.exists():
        raise ToolError(t("lint.path_missing", path=str(root)))
    findings, files = lint_path(root)
    if files == 0:
        raise ToolError(t("lint.no_files", path=str(root)))
    return _lint_report(findings, files, args)


def _lint_config(cfg: Config, args: argparse.Namespace) -> int:
    findings = []
    files = 0
    for folder, kind in ((cfg.tools_dir, "tools"), (cfg.functions_dir, "functions")):
        if not folder.is_dir():
            continue
        for file in sorted(folder.glob("*.py")):
            if file.name.startswith("__"):
                continue
            files += 1
            display = file.relative_to(cfg.base_dir).as_posix() if file.is_relative_to(cfg.base_dir) else str(file)
            source = file.read_text(encoding="utf-8", errors="replace")
            findings.extend(lint_source(display, kind, source, file_stem=file.stem))
    if files == 0:
        raise ToolError(t("lint.no_files", path=str(cfg.base_dir)))
    return _lint_report(findings, files, args)


def _lint_report(findings: list, files: int, args: argparse.Namespace) -> int:
    if args.json:
        print(render.lint_json(findings, files))
    else:
        for finding in findings:
            print(render.finding_text(finding))
        print(render.lint_summary(findings, files))
    errors = any(f.level == "error" for f in findings)
    warnings = any(f.level == "warning" for f in findings)
    return 1 if errors or (args.strict and warnings) else 0


def cmd_plan(args: argparse.Namespace) -> int:
    plan, _desired, client, label, mock, _cfg = _plan(args, prune=args.prune)
    with client:
        if args.json:
            if mock:
                _banner(label, mock, to_stderr=True)
            print(render.plan_json(plan, mock, label, show_diff=args.diff))
        else:
            _banner(label, mock)
            print(render.plan_text(plan, show_diff=args.diff))
    return 1 if plan.has_drift(args.fail_on_unmanaged) else 0


def _confirm() -> bool:
    answer = input(t("apply.confirm"))
    return answer.strip().lower() in ("y", "yes")


def cmd_apply(args: argparse.Namespace) -> int:
    plan, desired, client, label, mock, cfg = _plan(args, prune=args.prune)
    with client:
        _banner(label, mock)
        print(render.plan_text(plan))
        skipped = plan.summary["skipped"]
        if not plan.writes:
            print(t("apply.nothing"))
            return 1 if skipped else 0
        if not args.yes:
            if not sys.stdin.isatty():
                raise ToolError(t("apply.need_yes"))
            if not _confirm():
                print(t("apply.cancelled"))
                return 1
        message = args.message or git_short_hash(cfg.base_dir)
        result = apply_plan(client, plan, desired, message=message)
    for line in render.apply_lines(result):
        print(line)
    for rejection in result.rejected:
        item = next((d for d in desired if d.kind == rejection.kind and d.id == rejection.id), None)
        hints = []
        if item is not None:
            kind_dir = "tools" if item.kind == "tool" else "functions"
            hints = [f for f in lint_source(item.path.name, kind_dir, item.content, file_stem=item.path.stem) if f.level == "error"]
        if hints:
            for finding in hints:
                print(t("apply.hint_line", text=render.finding_text(finding)))
        else:
            print(t("apply.hint_generic", kind=rejection.kind, id=rejection.id))
    print(t("apply.summary", done=len(result.done), rejected=len(result.rejected)))
    return 1 if result.rejected or skipped else 0


def cmd_pull(args: argparse.Namespace) -> int:
    out = Path(args.out)
    config_path = out / DEFAULT_CONFIG_NAME
    cfg_url = None
    if config_path.is_file():
        cfg_url = load_config(config_path).url
    client, label, mock = _open_client(args, out, cfg_url)
    with client:
        _banner(label, mock)
        result = run_pull(client, out, config_path, url=None if mock else (args.url or os.environ.get("OWUI_URL") or cfg_url), force=args.force)
    for item in result.written:
        print(t("pull.written", item=item))
    for item in result.kept:
        print(t("pull.kept", item=item))
    for item in result.invalid_ids:
        print(t("pull.invalid_id", item=item))
    print(t("pull.summary", written=len(result.written), unchanged=len(result.unchanged), kept=len(result.kept)))
    if result.config_written:
        print(t("pull.config_written", path=str(result.config_written)))
    if result.config_kept:
        print(t("pull.config_kept", path=str(result.config_kept)))
        for kind, item_id, field_name, want, have in result.state_differences:
            print(t("pull.state_diff", item=f"{kind}:{item_id}", field=field_name,
                    want=str(want).lower(), have=str(have).lower()))
    if result.valves_dropped:
        print(t("pull.valves_dropped", n=result.valves_dropped))
    else:
        print(t("pull.valves_note"))
    return 0


COMMANDS = {"lint": cmd_lint, "plan": cmd_plan, "apply": cmd_apply, "pull": cmd_pull}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code (never raises for expected errors)."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    i18n.set_lang(i18n.resolve_lang(_preparse_lang(args_list), os.environ))
    _localize_argparse(i18n.get_lang())
    try:
        parser = build_parser()
        args = parser.parse_args(args_list)
        return COMMANDS[args.command](args)
    except SystemExit as exc:  # argparse: --help (0) or usage error (2)
        return int(exc.code or 0)
    except ToolError as exc:
        print(f"owui-deploy: {t('err.prefix')}: {exc.message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"owui-deploy: {t('err.interrupted')}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - last resort: a readable line instead of a traceback
        if os.environ.get("OWUI_DEPLOY_DEBUG"):
            traceback.print_exc()
        print(f"owui-deploy: {t('err.prefix')}: {t('err.internal', detail=f'{type(exc).__name__}: {exc}')}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
