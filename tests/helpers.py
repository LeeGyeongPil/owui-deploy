"""Shared helpers for the tests (importing this module pins the language to English)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

os.environ["OWUI_DEPLOY_LANG"] = "en"

from owui_deploy import i18n  # noqa: E402
from owui_deploy.applier import ApplyResult, apply_plan  # noqa: E402
from owui_deploy.client import OpenWebUIClient  # noqa: E402
from owui_deploy.config import Config, build_desired, load_config  # noqa: E402
from owui_deploy.fake import FakeOpenWebUI  # noqa: E402
from owui_deploy.planner import Plan, build_plan  # noqa: E402

i18n.set_lang("en")

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
FIXTURES = ROOT / "tests" / "fixtures" / "owui-0.13.3"


def fixture(name: str):
    """Load a recorded response: returns (status, body)."""
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data["status"], data["body"]


def source(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def demo_project(tmp_path: Path) -> Path:
    """Copy examples/demo into tmp_path and return the config file path."""
    target = tmp_path / "demo"
    shutil.copytree(EXAMPLES / "demo", target, ignore=shutil.ignore_patterns(".owui-deploy-fake.json"))
    return target / "owui-deploy.toml"


def client_for(fake: FakeOpenWebUI, token: str = "t") -> OpenWebUIClient:
    return OpenWebUIClient("http://fake.invalid", token, transport=fake.transport())


def make_plan(fake: FakeOpenWebUI, cfg: Config, prune: bool = False) -> tuple[Plan, list]:
    desired, skipped = build_desired(cfg)
    with client_for(fake) as client:
        remote = {kind: client.export_all(kind) for kind in ("tool", "function")}
    return build_plan(desired, skipped, remote, prune=prune), desired


def do_apply(fake: FakeOpenWebUI, config_path: Path, prune: bool = False, message: str | None = None) -> ApplyResult:
    cfg = load_config(config_path)
    plan, desired = make_plan(fake, cfg, prune=prune)
    with client_for(fake) as client:
        return apply_plan(client, plan, desired, message=message)
