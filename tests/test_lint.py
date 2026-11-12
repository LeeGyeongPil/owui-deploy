import json

from helpers import EXAMPLES
from owui_deploy import cli
from owui_deploy.lint import lint_path, lint_source

OK = '"""\ntitle: T\nversion: 1\n"""\n'


def codes_of(findings):
    return {f.code for f in findings}


def test_broken_examples_report_each_rule(capsys):
    findings, files = lint_path(EXAMPLES / "broken")
    assert files == 8
    assert {"OWD001", "OWD002", "OWD003", "OWD004", "OWD005", "OWD006", "OWD008", "OWD009"} <= codes_of(findings)
    by_file = {}
    for f in findings:
        by_file.setdefault(f.path, set()).add(f.code)
    assert by_file["functions/no_class.py"] == {"OWD002"}
    assert by_file["functions/two_classes.py"] == {"OWD003"}
    assert by_file["functions/bad_valves.py"] == {"OWD006"}
    assert by_file["functions/Bad-Name.py"] == {"OWD004"}
    assert by_file["functions/secret_default.py"] == {"OWD009"}
    assert by_file["functions/no_frontmatter.py"] == {"OWD005"}
    assert by_file["functions/syntax_error.py"] == {"OWD001"}
    assert by_file["tools/undocumented.py"] == {"OWD008"}
    # the syntax error points at the real line
    assert [f.line for f in findings if f.code == "OWD001"] == [8]

    assert cli.main(["lint", str(EXAMPLES / "broken")]) == 1
    out = capsys.readouterr().out
    assert "functions/no_class.py:1 OWD002 error:" in out
    assert "Lint: 8 file(s), 4 error(s), 5 warning(s)." in out


def test_demo_examples_have_no_errors(capsys):
    findings, files = lint_path(EXAMPLES / "demo")
    assert files == 3
    assert [f for f in findings if f.level == "error"] == []
    assert codes_of(findings) == {"OWD007"}  # pii_mask uses `from utils`
    assert cli.main(["lint", str(EXAMPLES / "demo")]) == 0
    assert "OWD007 warning" in capsys.readouterr().out


def test_lint_never_executes_code(tmp_path):
    marker = tmp_path / "ran.txt"
    folder = tmp_path / "functions"
    folder.mkdir()
    (folder / "evil.py").write_text(
        f'"""\ntitle: Evil\nversion: 1\n"""\nopen({str(marker)!r}, "w").write("x")\n\nclass Filter:\n    pass\n',
        encoding="utf-8",
    )
    findings, files = lint_path(tmp_path)
    assert files == 1 and findings == []
    assert not marker.exists()


def test_rule_details():
    # empty default is fine, non-secret names are fine
    src = OK + 'from pydantic import BaseModel\nclass Filter:\n    class Valves(BaseModel):\n        api_key: str = ""\n        mode: str = "fast"\n'
    assert lint_source("functions/a.py", "functions", src) == []
    # Field(default=...) is seen too
    src = OK + 'from pydantic import BaseModel, Field\nclass Filter:\n    class Valves(BaseModel):\n        token: str = Field(default="abc")\n'
    assert codes_of(lint_source("functions/a.py", "functions", src)) == {"OWD009"}
    # Valves inheriting from a local BaseModel subclass is fine
    src = OK + "from pydantic import BaseModel\nclass Base(BaseModel):\n    pass\nclass Filter:\n    class Valves(Base):\n        x: int = 1\n"
    assert lint_source("functions/a.py", "functions", src) == []
    # upper case id is only a warning, a bad id is an error
    assert [(f.code, f.level) for f in lint_source("functions/MyFilter.py", "functions", OK + "class Filter: ...\n")] == [("OWD004", "warning")]
    assert [(f.code, f.level) for f in lint_source("functions/my-filter.py", "functions", OK + "class Filter: ...\n")] == [("OWD004", "error")]
    # missing frontmatter keys
    findings = lint_source("tools/a.py", "tools", '"""\ntitle: T\n"""\nclass Tools: ...\n')
    assert [f.msg_key for f in findings] == ["lint.OWD005.missing"]
    # a tool needs class Tools, a function file does not count a Tools class
    assert codes_of(lint_source("tools/a.py", "tools", OK + "class Filter: ...\n")) == {"OWD002"}
    assert codes_of(lint_source("functions/a.py", "functions", OK + "class Tools: ...\n")) == {"OWD002"}
    # `from utils_x` gets the special message
    weird = lint_source("functions/a.py", "functions", OK + "from utils_x import y\nclass Filter: ...\n")
    assert [f.msg_key for f in weird] == ["lint.OWD007.weird"]
    # syntax errors still allow the text based rules
    broken = lint_source("functions/a.py", "functions", "def (:\n")
    assert {"OWD001", "OWD005"} <= codes_of(broken)


def test_strict_json_and_paths(tmp_path, capsys):
    assert cli.main(["lint", str(EXAMPLES / "demo"), "--strict"]) == 1
    capsys.readouterr()
    assert cli.main(["lint", str(EXAMPLES / "demo"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"] == {"files": 3, "errors": 0, "warnings": 1}
    assert data["findings"][0]["code"] == "OWD007"
    # a single file works, a missing path is a tool error
    assert cli.main(["lint", str(EXAMPLES / "broken" / "functions" / "no_class.py")]) == 1
    capsys.readouterr()
    assert cli.main(["lint", str(tmp_path / "nope")]) == 2
    assert "path not found" in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["lint", str(empty)]) == 2
