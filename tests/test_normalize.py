from helpers import fixture, source
from owui_deploy.frontmatter import parse_frontmatter
from owui_deploy.normalize import normalize


def test_matches_recorded_0_13_3_roundtrip():
    original = source("source_probe_filter.py")
    _, recorded = fixture("function_get")
    assert "from utils.misc" in original
    assert recorded["content"] == normalize(original)
    assert recorded["content"] != original  # the real server really rewrote it
    assert recorded["meta"]["manifest"] == parse_frontmatter(original)
    # tools: the recorded round trip is byte-identical when there is nothing to rewrite
    _, tool = fixture("tool_get")
    assert tool["content"] == normalize(source("source_probe_tool.py")) == source("source_probe_tool.py")


def test_rewrite_rules_and_idempotence():
    text = "from utils.a import b\nfrom apps import c\nfrom main import d\nfrom config import e\nfrom utils_x import y\n"
    once = normalize(text)
    assert "from open_webui.utils.a import b" in once
    assert "from open_webui.apps import c" in once
    assert "from open_webui.main import d" in once
    assert "from open_webui.config import e" in once
    assert "from open_webui.utils_x import y" in once  # plain str.replace, same as the server
    assert normalize(once) == once
