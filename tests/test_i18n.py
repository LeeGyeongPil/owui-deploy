import json
import re
from pathlib import Path

import pytest

from helpers import EXAMPLES, demo_project
from owui_deploy import cli, i18n
from owui_deploy.lint import lint_path

LOCALES = Path(__file__).resolve().parent.parent / "src" / "owui_deploy" / "locales"


def load(lang):
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_locale_keys_match():
    en, ko = load("en"), load("ko")
    assert set(en) == set(ko)
    # the same placeholders must exist in both languages
    for key in en:
        assert set(re.findall(r"{(\w+)}", en[key])) == set(re.findall(r"{(\w+)}", ko[key])), key
    # no empty messages
    assert all(en.values()) and all(ko.values())


def test_korean_messages_use_polite_style():
    ko = load("ko")
    sentences = [v for k, v in ko.items() if k.startswith(("err.", "config.", "apply.", "pull.")) and not k.endswith(("_line", "confirm"))]
    plain_endings = ("한다.", "이다.", "했다.", "않는다.", "없다.")
    assert [s for s in sentences if s.strip().endswith(plain_endings)] == []


def test_lang_precedence(monkeypatch):
    env = {"OWUI_DEPLOY_LANG": "ko", "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
    assert i18n.resolve_lang("en", env) == "en"  # --lang wins
    assert i18n.resolve_lang(None, env) == "ko"  # then OWUI_DEPLOY_LANG
    assert i18n.resolve_lang(None, {"LC_ALL": "ko_KR.UTF-8", "LC_MESSAGES": "en", "LANG": "en"}) == "ko"
    assert i18n.resolve_lang(None, {"LC_MESSAGES": "ko_KR.UTF-8", "LANG": "en_US.UTF-8"}) == "ko"
    assert i18n.resolve_lang(None, {"LANG": "ko_KR.UTF-8"}) == "ko"
    assert i18n.resolve_lang(None, {"LANG": "fr_FR.UTF-8"}) == "en"  # not Korean -> English
    assert i18n.resolve_lang(None, {}) == "en"
    assert i18n.resolve_lang("fr", {}) == "en"
    # through the CLI: environment decides when --lang is absent, --lang overrides it
    monkeypatch.setenv("OWUI_DEPLOY_LANG", "ko")
    assert cli.main(["lint", str(EXAMPLES / "demo")]) == 0
    assert i18n.get_lang() == "ko"
    assert cli.main(["--lang", "en", "lint", str(EXAMPLES / "demo")]) == 0
    assert i18n.get_lang() == "en"
    monkeypatch.delenv("OWUI_DEPLOY_LANG")
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    assert cli.main(["lint", str(EXAMPLES / "demo")]) == 0
    assert i18n.get_lang() == "ko"


def test_help_and_plan_in_both_languages(tmp_path, capsys):
    config = demo_project(tmp_path)
    # help
    assert cli.main(["--lang", "en", "--help"]) == 0
    help_en = capsys.readouterr().out
    assert "Lint, plan and apply Open WebUI Tools and Functions" in help_en
    assert cli.main(["--lang", "ko", "--help"]) == 0
    help_ko = capsys.readouterr().out
    assert "점검(lint)하고" in help_ko and "종료 코드" in help_ko
    assert "Lint, plan and apply" not in help_ko
    # --lang is accepted after the subcommand too, and sub-help is translated
    assert cli.main(["plan", "--help", "--lang", "ko"]) == 0
    assert "미관리가 아니라 삭제로 보여 줍니다" in capsys.readouterr().out

    # plan
    assert cli.main(["--lang", "en", "plan", "--config", str(config), "--fake"]) == 1
    plan_en = capsys.readouterr().out
    assert "Plan: 1 to create, 1 to update, 1 to change state, 1 unmanaged." in plan_en
    assert "only on the server" in plan_en
    assert cli.main(["--lang", "ko", "plan", "--config", str(config), "--fake"]) == 1
    plan_ko = capsys.readouterr().out
    assert "생성 1건, 수정 1건, 상태 변경 1건, 미관리 1건" in plan_ko
    assert "서버에만 있음" in plan_ko
    assert "practice mock" in plan_ko  # the English marker stays so that the start command is language independent
    assert "to create" not in plan_ko

    # lint
    assert cli.main(["--lang", "en", "lint", str(EXAMPLES / "broken")]) == 1
    lint_en = capsys.readouterr().out
    assert "no Pipe/Filter/Action/Event class found" in lint_en
    assert cli.main(["lint", "--lang", "ko", str(EXAMPLES / "broken")]) == 1
    lint_ko = capsys.readouterr().out
    assert "Pipe/Filter/Action/Event 클래스가 없습니다" in lint_ko
    assert "OWD002" in lint_ko  # codes stay stable in every language
    assert "점검 결과: 파일 8개, 오류 4건, 경고 5건입니다." in lint_ko


def test_errors_are_translated(tmp_path, capsys):
    assert cli.main(["--lang", "ko", "plan", "--config", str(tmp_path / "x.toml")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("owui-deploy: 오류: ") and "설정 파일이 없습니다" in err


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_every_key_used_in_code_exists(lang):
    catalog = load(lang)
    source = "\n".join(p.read_text(encoding="utf-8") for p in LOCALES.parent.glob("*.py"))
    used = set(re.findall(r'(?<![\w.])t\(\s*"([\w.]+)"', source))
    used |= {f"plan.part.{n}" for n in ("create", "update", "state", "delete", "unmanaged", "skipped")}
    used |= {f"field.{n}" for n in ("content", "name", "description", "active", "global")}
    # every lint finding produced by the examples (plus the special OWD007 variant) has a message
    findings, _ = lint_path(EXAMPLES)
    used |= {f.msg_key for f in findings}
    used |= {"lint.OWD007.weird", "lint.OWD004.case", "lint.OWD005.missing", "lint.OWD008.doc", "lint.OWD002.tools"}
    assert sorted(k for k in used if k not in catalog) == []
