import httpx

from helpers import client_for
from owui_deploy import cli
from owui_deploy.client import OpenWebUIClient
from owui_deploy.fake import FakeOpenWebUI
from owui_deploy.pull import pull


def all_text(folder):
    return "\n".join(p.read_text(encoding="utf-8") for p in folder.rglob("*") if p.is_file())


def test_pull_drops_valves_and_roundtrips(tmp_path, capsys):
    out = tmp_path / "owui"
    assert cli.main(["pull", "--fake", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert (out / "tools" / "clock.py").is_file()
    assert (out / "functions" / "pii_mask.py").is_file()
    assert (out / "functions" / "legacy_filter.py").is_file()
    assert "from open_webui.utils.misc" in (out / "functions" / "pii_mask.py").read_text()  # exported as stored
    assert (out / "owui-deploy.toml").is_file()
    # the seeded server holds api_key = dummy-not-secret in plain text; it must not reach any file or output
    assert "dummy-not-secret" not in all_text(out)
    assert "dummy-not-secret" not in text
    assert "Valves (settings and secrets) are not exported" in text
    # and the pulled folder is in sync with the server: plan exits 0, including active/global state
    assert cli.main(["plan", "--config", str(out / "owui-deploy.toml"), "--fake"]) == 0
    assert "Plan: no changes." in capsys.readouterr().out


def test_pull_never_asks_for_valves(tmp_path):
    fake = FakeOpenWebUI()
    requested = []

    def spy(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return fake.handle(request)

    out = tmp_path / "out"
    with OpenWebUIClient("http://fake.invalid", "t", transport=httpx.MockTransport(spy)) as client:
        pull(client, out, out / "owui-deploy.toml", url=None)
    assert requested and all("include_valves" not in url for url in requested)


def test_pull_drops_valves_even_if_the_server_sends_them(tmp_path):
    fake = FakeOpenWebUI()

    def handler(request: httpx.Request) -> httpx.Response:
        response = fake.handle(request)
        if request.url.path == "/api/v1/functions/export":
            body = response.json()
            for entry in body:
                entry["valves"] = {"api_key": "dummy-not-secret"}
            return httpx.Response(200, json=body)
        return response

    out = tmp_path / "out"
    with OpenWebUIClient("http://fake.invalid", "t", transport=httpx.MockTransport(handler)) as client:
        result = pull(client, out, out / "owui-deploy.toml", url="http://localhost:8080")
    assert result.valves_dropped == 2  # the two seeded Functions
    assert "dummy-not-secret" not in all_text(out)
    assert 'url = "http://localhost:8080"' in (out / "owui-deploy.toml").read_text()


def test_pull_keeps_existing_config(tmp_path, capsys):
    out = tmp_path / "owui"
    out.mkdir()
    config = out / "owui-deploy.toml"
    original = '[defaults]\nactive = false\n# my own comment\n'
    config.write_text(original, encoding="utf-8")
    assert cli.main(["pull", "--fake", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert config.read_text(encoding="utf-8") == original  # never overwritten
    assert "kept existing config file" in text
    assert "config differs from the server: function:legacy_filter active False -> server True" in text
    # a differing local file is kept unless --force is given
    target = out / "tools" / "clock.py"
    target.write_text("# my local edit\n", encoding="utf-8")
    assert cli.main(["pull", "--fake", "--out", str(out)]) == 0
    assert target.read_text(encoding="utf-8") == "# my local edit\n"
    assert "kept local file" in capsys.readouterr().out
    assert cli.main(["pull", "--fake", "--out", str(out), "--force"]) == 0
    assert "class Tools" in target.read_text(encoding="utf-8")


def test_pull_skips_unsafe_ids(tmp_path):
    fake = FakeOpenWebUI()
    fake.items["function"]["../evil"] = {**fake.items["function"]["legacy_filter"], "id": "../evil"}
    out = tmp_path / "out"
    with client_for(fake) as client:
        result = pull(client, out, out / "owui-deploy.toml", url=None)
    assert result.invalid_ids == ["../evil"]
    assert not (tmp_path / "evil.py").exists()
