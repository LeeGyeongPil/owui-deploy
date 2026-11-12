import subprocess
import sys

import pytest

from helpers import demo_project, do_apply, make_plan
from owui_deploy import cli
from owui_deploy.applier import git_short_hash
from owui_deploy.config import load_config
from owui_deploy.fake import FakeOpenWebUI


def test_apply_twice_is_noop(tmp_path):
    config = demo_project(tmp_path)
    fake = FakeOpenWebUI()
    first = do_apply(fake, config)
    assert first.rejected == []
    assert {a for a, _, _ in first.done} == {"create", "update", "toggle", "toggle_global"}
    fake.log.clear()
    second = do_apply(fake, config)
    assert second.done == [] and second.rejected == []
    assert fake.writes() == []  # zero create/update/toggle/delete requests on the second run
    # final state equals the declaration
    functions = fake.items["function"]
    assert (functions["pii_mask"]["is_active"], functions["pii_mask"]["is_global"]) == (True, True)
    assert (functions["shout_action"]["is_active"], functions["shout_action"]["is_global"]) == (True, False)
    assert fake.items["tool"]["clock"]["is_active"] is True
    # and a plan afterwards has no drift (the server-only item is only informational)
    plan, _ = make_plan(fake, load_config(config))
    assert not plan.has_drift()


def test_apply_twice_through_the_cli(tmp_path, capsys):
    config = demo_project(tmp_path)
    args = ["--config", str(config), "--fake"]
    assert cli.main(["apply", "--yes", *args]) == 0
    capsys.readouterr()
    assert cli.main(["apply", "--yes", *args]) == 0
    assert "No changes." in capsys.readouterr().out
    assert cli.main(["plan", *args]) == 0  # unmanaged legacy_filter is only informational


def test_toggle_only_when_state_differs(tmp_path):
    config = demo_project(tmp_path)
    fake = FakeOpenWebUI()
    fake.items["function"]["pii_mask"]["is_active"] = True  # already active, still not global
    fake.log.clear()
    do_apply(fake, config)
    toggles = [entry for entry in fake.log if entry[1].endswith("/toggle")]
    global_toggles = [entry for entry in fake.log if entry[1].endswith("/toggle/global")]
    assert [p for _, p in toggles] == ["/api/v1/functions/id/shout_action/toggle"]
    assert [p for _, p in global_toggles] == ["/api/v1/functions/id/pii_mask/toggle/global"]


def test_commit_message_sent(tmp_path):
    config = demo_project(tmp_path)
    fake = FakeOpenWebUI()
    do_apply(fake, config, message="deploy abc123")
    update_bodies = [body for _, path, body in fake.bodies if path.endswith("/update")]
    assert update_bodies and all(body["commit_message"] == "deploy abc123" for body in update_bodies)
    assert fake.history[-1]["commit_message"] == "deploy abc123"
    create_bodies = [body for _, path, body in fake.bodies if path.endswith("/create")]
    assert create_bodies and "commit_message" not in create_bodies[0]


def test_commit_message_from_git_hash(tmp_path, capsys):
    config = demo_project(tmp_path)
    repo = config.parent
    try:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "chore: init"],
            cwd=repo, check=True, capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not usable here")
    short = git_short_hash(repo)
    assert short and len(short) >= 7
    assert cli.main(["apply", "--yes", "--config", str(config), "--fake"]) == 0
    state = repo / ".owui-deploy-fake.json"
    import json

    history = json.loads(state.read_text())["history"]
    assert any(entry["commit_message"] == short for entry in history)


def test_git_hash_missing_repo_returns_none(tmp_path):
    assert git_short_hash(tmp_path / "does-not-exist") is None


def test_never_calls_sync_and_prune_is_explicit(tmp_path):
    config = demo_project(tmp_path)
    fake = FakeOpenWebUI()
    do_apply(fake, config)
    assert not any(path.endswith("/sync") for _, path in fake.log)
    assert not any(method == "DELETE" for method, _ in fake.log)
    assert "legacy_filter" in fake.items["function"]  # server-only item survives without --prune

    fake.log.clear()
    do_apply(fake, config, prune=True)
    deletes = [(m, p) for m, p in fake.log if m == "DELETE"]
    assert deletes == [("DELETE", "/api/v1/functions/id/legacy_filter/delete")]
    assert "legacy_filter" not in fake.items["function"]
    assert set(fake.items["function"]) == {"pii_mask", "shout_action"}  # nothing else was touched
    assert set(fake.items["tool"]) == {"clock"}
    assert not any(path.endswith("/sync") for _, path in fake.log)


def test_requires_yes_when_not_tty(tmp_path, capsys, monkeypatch):
    config = demo_project(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    code = cli.main(["apply", "--config", str(config), "--fake"])
    captured = capsys.readouterr()
    assert code == 2
    assert "--yes" in captured.err and "nothing was changed" in captured.err
    assert not (config.parent / ".owui-deploy-fake.json").exists()  # not a single write happened


def test_interactive_confirmation(tmp_path, capsys, monkeypatch):
    config = demo_project(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["apply", "--config", str(config), "--fake"]) == 1
    assert "Cancelled" in capsys.readouterr().out
    assert not (config.parent / ".owui-deploy-fake.json").exists()
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert cli.main(["apply", "--config", str(config), "--fake"]) == 0
    assert (config.parent / ".owui-deploy-fake.json").exists()


def test_nothing_to_write_needs_no_yes(tmp_path, capsys, monkeypatch):
    config = demo_project(tmp_path)
    assert cli.main(["apply", "--yes", "--config", str(config), "--fake"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert cli.main(["apply", "--config", str(config), "--fake"]) == 0
    assert "No changes." in capsys.readouterr().out
