import httpx
import pytest

from helpers import demo_project
from owui_deploy import cli
from owui_deploy.client import OpenWebUIClient
from owui_deploy.fake import FakeOpenWebUI


def inject_transport(monkeypatch, transport):
    """Make the CLI talk to ``transport`` instead of a real network connection."""

    def factory(base_url, token, **kwargs):
        return OpenWebUIClient(base_url, token, transport=transport)

    monkeypatch.setattr(cli, "OpenWebUIClient", factory)


def refuse(request):
    raise httpx.ConnectError("Connection refused", request=request)


def respond(status):
    return lambda request: httpx.Response(status, json={"detail": "Not authenticated"})


def assert_one_line_error(captured, needle):
    assert captured.err.startswith("owui-deploy: error: ")
    assert needle in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "Traceback" not in captured.err + captured.out


def test_tool_errors_exit_2(tmp_path, capsys, monkeypatch):
    config = demo_project(tmp_path)

    # config file missing
    assert cli.main(["plan", "--config", str(tmp_path / "missing.toml"), "--fake"]) == 2
    assert_one_line_error(capsys.readouterr(), "config file not found")

    # invalid TOML and unknown keys
    broken = tmp_path / "broken.toml"
    broken.write_text("[server\nurl=", encoding="utf-8")
    assert cli.main(["plan", "--config", str(broken), "--fake"]) == 2
    assert_one_line_error(capsys.readouterr(), "cannot read")
    unknown = tmp_path / "unknown.toml"
    unknown.write_text("[serverr]\nurl = 'x'\n", encoding="utf-8")
    assert cli.main(["plan", "--config", str(unknown), "--fake"]) == 2
    assert_one_line_error(capsys.readouterr(), "unknown key")

    # token missing (real mode)
    assert cli.main(["plan", "--config", str(config)]) == 2
    assert_one_line_error(capsys.readouterr(), "OWUI_TOKEN")

    # URL missing
    no_url = tmp_path / "no_url.toml"
    no_url.write_text("", encoding="utf-8")
    monkeypatch.setenv("OWUI_TOKEN", "tok")
    assert cli.main(["plan", "--config", str(no_url)]) == 2
    assert_one_line_error(capsys.readouterr(), "no server URL")

    # connection refused
    inject_transport(monkeypatch, httpx.MockTransport(refuse))
    assert cli.main(["plan", "--config", str(config)]) == 2
    assert_one_line_error(capsys.readouterr(), "cannot connect to http://localhost:8080")

    # 401 and 403 (the real server answers 403 for forbidden API keys)
    for status in (401, 403):
        inject_transport(monkeypatch, httpx.MockTransport(respond(status)))
        assert cli.main(["plan", "--config", str(config)]) == 2
        err = capsys.readouterr()
        assert_one_line_error(err, f"HTTP {status}")
        assert "ENABLE_API_KEYS=true" in err.err

    # a server that is not Open WebUI
    inject_transport(monkeypatch, httpx.MockTransport(lambda request: httpx.Response(200, text="<html>")))
    assert cli.main(["plan", "--config", str(config)]) == 2
    assert_one_line_error(capsys.readouterr(), "did not answer")

    # unexpected shape
    inject_transport(monkeypatch, httpx.MockTransport(lambda request: httpx.Response(200, json={"oops": 1})))
    assert cli.main(["plan", "--config", str(config)]) == 2
    assert_one_line_error(capsys.readouterr(), "unexpected shape")


def test_wrong_token_against_fake_server_exits_2(tmp_path, capsys, monkeypatch):
    config = demo_project(tmp_path)
    monkeypatch.setenv("OWUI_TOKEN", "wrong")
    inject_transport(monkeypatch, FakeOpenWebUI(token="right").transport())
    assert cli.main(["apply", "--yes", "--config", str(config)]) == 2
    assert_one_line_error(capsys.readouterr(), "HTTP 401")


def test_url_priority(tmp_path, monkeypatch, capsys):
    config = demo_project(tmp_path)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=[])

    monkeypatch.setenv("OWUI_TOKEN", "tok")
    inject_transport(monkeypatch, httpx.MockTransport(handler))
    cli.main(["plan", "--config", str(config)])
    assert seen[0].startswith("http://localhost:8080/")  # config
    monkeypatch.setenv("OWUI_URL", "http://env.example:1")
    seen.clear()
    cli.main(["plan", "--config", str(config)])
    assert seen[0].startswith("http://env.example:1/")  # env beats config
    seen.clear()
    cli.main(["plan", "--config", str(config), "--url", "http://flag.example:2"])
    assert seen[0].startswith("http://flag.example:2/")  # flag beats env
    capsys.readouterr()


def test_server_rejection_exits_1(tmp_path, capsys):
    config = demo_project(tmp_path)
    # a Function the server will refuse (no class) next to valid changes
    (config.parent / "functions" / "no_class.py").write_text(
        '"""\ntitle: No Class\nversion: 1\n"""\n\n\ndef inlet(body):\n    return body\n', encoding="utf-8"
    )
    code = cli.main(["apply", "--yes", "--config", str(config), "--fake"])
    out = capsys.readouterr().out
    assert code == 1
    assert "rejected by the server: create function no_class (HTTP 400: [ERROR: Error creating function])" in out
    assert "hint: no_class.py:1 OWD002 error" in out  # the lint hint explains the real reason
    assert "Apply: " in out and "1 rejected" in out
    # the other items were still applied
    fake = FakeOpenWebUI(state_path=config.parent / ".owui-deploy-fake.json")
    assert "shout_action" in fake.items["function"] and "no_class" not in fake.items["function"]
    assert fake.items["function"]["pii_mask"]["is_global"] is True
    assert fake.items["tool"]["clock"]["meta"]["manifest"]["version"] == "0.2.0"


def test_argparse_errors_exit_2(capsys):
    assert cli.main(["plan", "--bogus"]) == 2
    assert "unrecognized arguments" in capsys.readouterr().err
    assert cli.main([]) == 2
    err = capsys.readouterr().err
    assert "required" in err or "arguments are required" in err
    assert cli.main(["--lang", "fr", "lint"]) == 2


def test_help_and_version_exit_0(capsys):
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "lint" in out and "exit codes" in out
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("owui-deploy ")


def test_no_traceback_on_unexpected_error(tmp_path, capsys, monkeypatch):
    config = demo_project(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "build_desired", boom)
    assert cli.main(["plan", "--config", str(config), "--fake"]) == 2
    err = capsys.readouterr().err
    assert "kaboom" in err and "Traceback" not in err


@pytest.mark.parametrize("flag", ["--fake"])
def test_state_file_is_only_written_by_writes(tmp_path, flag):
    config = demo_project(tmp_path)
    assert cli.main(["plan", "--config", str(config), flag]) == 1
    assert not (config.parent / ".owui-deploy-fake.json").exists()


def test_non_utf8_file_gives_one_line_error(tmp_path, capsys):
    config = demo_project(tmp_path)
    (config.parent / "functions" / "latin.py").write_bytes(b"\xff\xfe bad")
    assert cli.main(["plan", "--fake", "--config", str(config)]) == 2
    captured = capsys.readouterr()
    assert_one_line_error(captured, "latin.py")
    assert "UTF-8" in captured.err


def test_config_without_folder_is_reported(tmp_path, capsys):
    (tmp_path / "owui-deploy.toml").write_text("[functions.nope]\nglobal = true\n", encoding="utf-8")
    assert cli.main(["plan", "--fake", "--config", str(tmp_path / "owui-deploy.toml")]) == 1
    assert "nope" in capsys.readouterr().out


def test_missing_configured_folder_is_reported(tmp_path, capsys):
    (tmp_path / "owui-deploy.toml").write_text('[paths]\nfunctions = "fucntions"\n', encoding="utf-8")
    assert cli.main(["plan", "--fake", "--config", str(tmp_path / "owui-deploy.toml")]) == 1
    assert "fucntions" in capsys.readouterr().out


def test_url_without_scheme_is_a_bad_url(monkeypatch, tmp_path, capsys):
    config = demo_project(tmp_path)
    monkeypatch.setenv("OWUI_TOKEN", "t")
    assert cli.main(["plan", "--config", str(config), "--url", "notaurl"]) == 2
    assert_one_line_error(capsys.readouterr(), "invalid server URL")


def test_korean_help_and_usage_errors_are_translated(capsys):
    assert cli.main(["--lang", "ko", "plan", "--bogus"]) == 2
    err = capsys.readouterr().err
    assert "사용법: " in err and "unrecognized" not in err
    assert cli.main(["--lang", "ko", "plan", "--help"]) == 0
    out = capsys.readouterr().out
    assert "옵션" in out and "options:" not in out
    cli.main(["--lang", "en", "plan", "--help"])
    assert "options:" in capsys.readouterr().out
