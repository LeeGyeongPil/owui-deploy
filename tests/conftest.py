"""Test setup: fixed language, no proxy variables, in-process mock server only."""

import os

# Fix the output language and neutralise the sandbox/CI proxy before anything else is imported.
os.environ["OWUI_DEPLOY_LANG"] = "en"
for _name in ("LC_ALL", "LC_MESSAGES", "LANG", "OWUI_URL", "OWUI_TOKEN", "OWUI_DEPLOY_DEBUG"):
    os.environ.pop(_name, None)
for _name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(_name, None)
os.environ["NO_PROXY"] = "*"

import pytest  # noqa: E402

from owui_deploy import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def _fixed_language(monkeypatch):
    monkeypatch.setenv("OWUI_DEPLOY_LANG", "en")
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "OWUI_URL", "OWUI_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    i18n.set_lang("en")
    yield
    i18n.set_lang("en")
