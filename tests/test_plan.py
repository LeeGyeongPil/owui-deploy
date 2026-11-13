import json
import os
import shutil
import subprocess
import sys

import pytest
from helpers import EXAMPLES, demo_project, make_plan
from owui_deploy import cli
from owui_deploy.config import build_desired, load_config
from owui_deploy.errors import ConfigError
from owui_deploy.fake import SEED_PII_MASK, FakeOpenWebUI


def changes_by_action(plan):
    result = {}
    for change in plan.changes:
        result.setdefault(change.action, []).append(change)
    return result


def test_plan_against_seeded_fake(tmp_path, capsys):
    config = demo_project(tmp_path)
    plan, _ = make_plan(FakeOpenWebUI(), load_config(config))
    by_action = changes_by_action(plan)
    assert [(c.kind, c.id) for c in by_action["create"]] == [("function", "shout_action")]
    assert [(c.kind, c.id, c.fields) for c in by_action["update"]] == [("tool", "clock", ["content", "description"])]
    assert [(c.id, c.fields) for c in by_action["state"]] == [("pii_mask", ["active", "global"])]
    assert [(c.kind, c.id) for c in by_action["unmanaged"]] == [("function", "legacy_filter")]
    assert plan.summary == {"create": 1, "update": 1, "state": 1, "delete": 0, "unmanaged": 1, "skipped": 0}
    assert plan.has_drift()

    code = cli.main(["plan", "--config", str(config), "--fake"])
    out = capsys.readouterr().out
    assert code == 1
    assert "practice mock" in out
    for symbol_line in ("+ create", "~ update", "~ state", "? unmanaged"):
        assert symbol_line in out
    assert "Plan: 1 to create, 1 to update, 1 to change state, 1 unmanaged." in out
    assert "active: false -> true" in out


def test_name_and_description_changes_are_updates(tmp_path):
    config = demo_project(tmp_path)
    config.write_text(config.read_text() + '\n[functions.legacy_filter]\nname = "Renamed"\n', encoding="utf-8")
    (config.parent / "functions" / "legacy_filter.py").write_text(
        '"""\ntitle: Legacy Filter\nversion: 0.0.1\n"""\n\n\nclass Filter:\n    def inlet(self, body: dict) -> dict:\n        return body\n',
        encoding="utf-8",
    )
    plan, _ = make_plan(FakeOpenWebUI(), load_config(config))
    update = [c for c in plan.changes if c.id == "legacy_filter"]
    assert [(c.action, c.fields) for c in update] == [("update", ["name"])]


def test_import_rewrite_is_not_drift(tmp_path):
    folder = tmp_path / "proj"
    (folder / "functions").mkdir(parents=True)
    (folder / "functions" / "pii_mask.py").write_text(SEED_PII_MASK, encoding="utf-8")
    config = folder / "owui-deploy.toml"
    config.write_text("[defaults]\nactive = false\n", encoding="utf-8")
    fake = FakeOpenWebUI()
    remote = fake.items["function"]["pii_mask"]["content"]
    assert "from utils.misc" in SEED_PII_MASK
    assert "from open_webui.utils.misc" in remote  # the server rewrote it
    plan, _ = make_plan(fake, load_config(config))
    assert [c for c in plan.changes if c.id == "pii_mask"] == []  # and that is not reported
    assert cli.main(["plan", "--config", str(config), "--fake", "--fail-on-unmanaged"]) == 1  # only unmanaged items remain


def test_json_shape(tmp_path, capsys):
    config = demo_project(tmp_path)
    code = cli.main(["plan", "--json", "--diff", "--config", str(config), "--fake"])
    captured = capsys.readouterr()
    assert code == 1
    assert "practice mock" in captured.err  # keeps stdout pure JSON
    data = json.loads(captured.out)
    assert set(data) >= {"changes", "summary", "mock", "server"}
    assert data["mock"] is True
    for change in data["changes"]:
        assert set(change) >= {"kind", "id", "action", "fields"}
    assert data["summary"]["create"] == 1 and data["summary"]["unmanaged"] == 1
    update = next(c for c in data["changes"] if c["action"] == "update")
    assert "+description: Tell the model the current time" in update["diff"]


def test_clean_plan_exits_zero(tmp_path, capsys):
    config = demo_project(tmp_path)
    assert cli.main(["apply", "--yes", "--prune", "--config", str(config), "--fake"]) == 0
    capsys.readouterr()
    assert cli.main(["plan", "--config", str(config), "--fake"]) == 0
    assert "Plan: no changes." in capsys.readouterr().out


def test_invalid_file_names_are_skipped_and_reported(tmp_path, capsys):
    config = demo_project(tmp_path)
    (config.parent / "functions" / "Bad-Name.py").write_text("x = 1\n", encoding="utf-8")
    assert cli.main(["plan", "--config", str(config), "--fake"]) == 1
    out = capsys.readouterr().out
    assert "! skip" in out and "Bad-Name" in out and "1 skipped" in out


# --- config keys are case-insensitive (ids are lowercased by the server) ---


def _mixed_case_project(tmp_path, toml_text):
    (tmp_path / "functions").mkdir()
    shutil.copy(EXAMPLES / "demo" / "functions" / "shout_action.py", tmp_path / "functions" / "MyShout.py")
    cfg_path = tmp_path / "owui-deploy.toml"
    cfg_path.write_text(toml_text, encoding="utf-8")
    return cfg_path


def test_mixed_case_config_key_applies_global(tmp_path):
    cfg = load_config(_mixed_case_project(tmp_path, "[functions.MyShout]\nglobal = true\n"))
    items, skipped = build_desired(cfg)
    assert skipped == []
    assert [(i.id, i.is_global) for i in items] == [("myshout", True)]


def test_mixed_case_duplicate_keys_are_a_config_error(tmp_path):
    path = _mixed_case_project(tmp_path, "[functions.MyShout]\nglobal = true\n[functions.myshout]\nactive = false\n")
    with pytest.raises(ConfigError) as err:
        load_config(path)
    assert "MyShout" in str(err.value) and "myshout" in str(err.value)


def test_mixed_case_duplicate_keys_exit_two(tmp_path):
    path = _mixed_case_project(tmp_path, "[functions.MyShout]\n[functions.myshout]\n")
    env = {**os.environ, "LANG": "C", "OWUI_DEPLOY_LANG": "en"}
    proc = subprocess.run(
        [sys.executable, "-m", "owui_deploy", "plan", "--config", str(path), "--fake"],
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
    )
    assert proc.returncode == 2


def test_config_key_without_file_is_still_reported_with_written_key(tmp_path):
    cfg = load_config(_mixed_case_project(tmp_path, "[functions.MyShout]\n[functions.Ghost]\n"))
    _, skipped = build_desired(cfg)
    assert [(s.reason_key, s.params["id"]) for s in skipped] == [("skip.config_without_file", "Ghost")]


def test_mixed_case_key_apply_then_plan_is_clean(tmp_path):
    path = _mixed_case_project(tmp_path, "[functions.MyShout]\nglobal = true\n")
    env = {**os.environ, "LANG": "C", "OWUI_DEPLOY_LANG": "en"}

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "owui_deploy", *args, "--config", str(path), "--fake"],
            capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
        )

    applied = run("apply", "--yes")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    state = json.loads((tmp_path / ".owui-deploy-fake.json").read_text(encoding="utf-8"))
    assert "true" in json.dumps(state).lower()
    assert run("plan").returncode == 0
