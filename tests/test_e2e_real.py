"""Optional end-to-end check against a real Open WebUI (skipped unless OWUI_E2E_URL and OWUI_E2E_TOKEN are set).

Start a throw-away server (Open WebUI 0.13.3, Python 3.11/3.12):

    uv venv --python 3.11 .venv-owui && VIRTUAL_ENV=.venv-owui uv pip install open-webui==0.13.3
    OFFLINE_MODE=true ENABLE_OLLAMA_API=false ENABLE_OPENAI_API=false .venv-owui/bin/open-webui serve --port 8099

Then sign up the first (admin) user in the browser, copy the JWT and run:

    OWUI_E2E_URL=http://127.0.0.1:8099 OWUI_E2E_TOKEN=<jwt> uv run pytest tests/test_e2e_real.py
"""

import os

import pytest

from helpers import demo_project
from owui_deploy import cli

URL = os.environ.get("OWUI_E2E_URL")
TOKEN = os.environ.get("OWUI_E2E_TOKEN")

pytestmark = pytest.mark.skipif(not (URL and TOKEN), reason="OWUI_E2E_URL and OWUI_E2E_TOKEN are not set")


def test_real_server_roundtrip(tmp_path, monkeypatch, capsys):
    config = demo_project(tmp_path)
    # the real server executes uploaded code, so only the harmless demo files are used
    (config.parent / "functions" / "pii_mask.py").unlink()
    config.write_text(config.read_text().replace("[functions.pii_mask]\nglobal = true     # a Filter that should run for every model\n", ""), encoding="utf-8")
    monkeypatch.setenv("OWUI_URL", URL)
    monkeypatch.setenv("OWUI_TOKEN", TOKEN)
    args = ["--config", str(config)]
    assert cli.main(["apply", "--yes", "-m", "e2e", *args]) == 0
    capsys.readouterr()
    assert cli.main(["apply", "--yes", *args]) == 0
    assert "No changes." in capsys.readouterr().out
    assert cli.main(["plan", *args]) == 0
    assert cli.main(["apply", "--yes", "--prune", "--message", "cleanup", *args]) == 0
