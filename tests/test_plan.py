import json

from helpers import demo_project, make_plan
from owui_deploy import cli
from owui_deploy.config import load_config
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
