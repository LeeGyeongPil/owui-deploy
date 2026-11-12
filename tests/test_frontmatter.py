from helpers import fixture, source
from owui_deploy.frontmatter import parse_frontmatter


def test_matches_server_rules():
    # recorded 0.13.3 manifests equal our parser's result for the uploaded sources
    _, tool = fixture("tool_get")
    assert tool["meta"]["manifest"] == parse_frontmatter(source("source_probe_tool.py"))
    _, func = fixture("function_get")
    assert func["meta"]["manifest"] == parse_frontmatter(source("source_probe_filter.py"))
    # first line must be exactly three double quotes (outer spaces are ignored by the server)
    assert parse_frontmatter("'''\ntitle: x\n'''\n") == {}
    assert parse_frontmatter('# comment\n"""\ntitle: x\n"""\n') == {}
    assert parse_frontmatter('  """  \ntitle: x\n"""\n') == {"title": "x"}
    assert parse_frontmatter("") == {}
    # keys are [a-z_]+ (case-insensitive), values are stripped, parsing stops at the closing quotes
    text = '"""\ntitle:  My Tool \nrequired_open_webui_version: 0.4.0\nnot a key\nbad-key: 1\n"""\nother: 2\n'
    assert parse_frontmatter(text) == {"title": "My Tool", "required_open_webui_version": "0.4.0"}
    # a key with an empty value is kept as an empty string (like "requirements:" in the recording)
    assert parse_frontmatter('"""\nrequirements:\n"""\n') == {"requirements": ""}
