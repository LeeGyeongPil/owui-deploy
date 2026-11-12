"""The practice mock must keep the contract of the responses recorded from Open WebUI 0.13.3."""

import httpx
import pytest

from helpers import client_for, fixture, source
from owui_deploy.errors import ApiError
from owui_deploy.fake import FakeOpenWebUI


@pytest.fixture
def empty_fake():
    fake = FakeOpenWebUI()
    for kind in ("tool", "function"):
        fake.items[kind].clear()
    fake.valves.clear()
    fake.log.clear()
    return fake


def payload(item_id, content, description="d", name=None):
    return {"id": item_id, "name": name or item_id, "content": content, "meta": {"description": description}}


def keys(body):
    return set(body[0] if isinstance(body, list) else body)


def test_response_key_sets_match_recordings(empty_fake):
    fake = empty_fake
    with client_for(fake) as c:
        # Tool
        created = c.create("tool", payload("probe_clock", source("source_probe_tool.py")))
        assert keys(created) == keys(fixture("tool_create")[1])
        assert set(created["meta"]) == set(fixture("tool_create")[1]["meta"])
        assert keys(c.get("tool", "probe_clock")) == keys(fixture("tool_get")[1])
        updated = c.update("tool", "probe_clock", {**payload("probe_clock", source("source_probe_tool.py")), "commit_message": "bump"})
        assert keys(updated) == keys(fixture("tool_update")[1])
        assert keys(c.toggle("tool", "probe_clock")) == keys(fixture("tool_toggle")[1])
        assert keys(c.export_all("tool")) == keys(fixture("tool_export")[1])
        # Function
        created = c.create("function", payload("probe_filter", source("source_probe_filter.py")))
        assert keys(created) == keys(fixture("function_create")[1])
        assert set(created["meta"]) == set(fixture("function_create")[1]["meta"])
        assert keys(c.get("function", "probe_filter")) == keys(fixture("function_get")[1])
        assert keys(c.toggle("function", "probe_filter")) == keys(fixture("function_toggle_active")[1])
        assert keys(c.toggle_global("probe_filter")) == keys(fixture("function_toggle_global")[1])
        updated = c.update("function", "probe_filter", payload("probe_filter", source("source_probe_filter.py")))
        assert keys(updated) == keys(fixture("function_update")[1])
        assert keys(c.export_all("function")) == keys(fixture("function_export_with_valves")[1]) - {"valves"}
    response = httpx.Client(transport=fake.transport(), base_url="http://x").get("/api/v1/functions/export", params={"include_valves": "true"})
    assert keys(response.json()) == keys(fixture("function_export_with_valves")[1])


def test_content_is_rewritten_like_the_server(empty_fake):
    with client_for(empty_fake) as c:
        c.create("function", payload("probe_filter", source("source_probe_filter.py")))
        got = c.get("function", "probe_filter")
    recorded = fixture("function_get")[1]
    assert got["content"] == recorded["content"]
    assert got["type"] == recorded["type"] == "filter"
    assert got["meta"]["manifest"] == recorded["meta"]["manifest"]


def test_new_items_start_in_the_recorded_state(empty_fake):
    with client_for(empty_fake) as c:
        func = c.create("function", payload("probe_filter", source("source_probe_filter.py")))
        tool = c.create("tool", payload("probe_clock", source("source_probe_tool.py")))
    recorded = fixture("function_create")[1]
    assert (func["is_active"], func["is_global"]) == (recorded["is_active"], recorded["is_global"]) == (False, False)
    assert tool["is_active"] is fixture("tool_create")[1]["is_active"] is True


def test_toggles_flip_instead_of_set(empty_fake):
    with client_for(empty_fake) as c:
        c.create("function", payload("probe_filter", source("source_probe_filter.py")))
        assert c.toggle("function", "probe_filter")["is_active"] is fixture("function_toggle_active")[1]["is_active"]
        assert c.toggle("function", "probe_filter")["is_active"] is False  # second call flips back
        assert c.toggle_global("probe_filter")["is_global"] is fixture("function_toggle_global")[1]["is_global"]
        assert c.toggle_global("probe_filter")["is_global"] is False


def test_update_keeps_state(empty_fake):
    with client_for(empty_fake) as c:
        c.create("function", payload("probe_filter", source("source_probe_filter.py")))
        c.toggle("function", "probe_filter")
        c.toggle_global("probe_filter")
        updated = c.update("function", "probe_filter", payload("probe_filter", source("source_probe_filter.py").replace("0.1.0", "0.2.0")))
    assert (updated["is_active"], updated["is_global"]) == (True, True)
    assert fixture("function_update")[1]["is_active"] is True
    assert updated["meta"]["manifest"]["version"] == "0.2.0"


@pytest.mark.parametrize(
    ("item_id", "content", "recording"),
    [
        ("probe_broken", "source_broken.py", "function_create_broken"),
        ("bad-id", "source_probe_filter.py", "function_create_bad_id"),
    ],
)
def test_rejections_match_recordings(empty_fake, item_id, content, recording):
    status, body = fixture(recording)
    with client_for(empty_fake) as c, pytest.raises(ApiError) as caught:
        c.create("function", payload(item_id, source(content)))
    assert (caught.value.status, caught.value.detail) == (status, body["detail"]) == (400, body["detail"])


def test_duplicate_id_is_rejected(empty_fake):
    status, body = fixture("function_create_duplicate")
    with client_for(empty_fake) as c:
        c.create("function", payload("probe_filter", source("source_probe_filter.py")))
        with pytest.raises(ApiError) as caught:
            c.create("function", payload("probe_filter", source("source_probe_filter.py")))
    assert (caught.value.status, caught.value.detail) == (status, body["detail"])
    assert fixture("function_create_broken")[1]["detail"] == "[ERROR: Error creating function]"


def test_sync_with_partial_list_deletes_the_rest(empty_fake):
    action = payload("probe_action", '"""\ntitle: Probe Action\n"""\nclass Action:\n    pass\n')
    with client_for(empty_fake) as c:
        c.create("function", payload("probe_filter", source("source_probe_filter.py")))
        c.create("function", action)
    http = httpx.Client(transport=empty_fake.transport(), base_url="http://x")
    response = http.post("/api/v1/functions/sync", json={"functions": [action]})
    recorded_status, recorded = fixture("function_sync_partial")
    assert response.status_code == recorded_status
    assert [f["id"] for f in response.json()] == [f["id"] for f in recorded] == ["probe_action"]
    assert keys(response.json()) == keys(recorded)
    assert list(empty_fake.items["function"]) == ["probe_action"]
    assert [f["id"] for f in fixture("function_list_after_sync")[1]] == ["probe_action"]


def test_export_valves_only_when_requested():
    fake = FakeOpenWebUI()
    http = httpx.Client(transport=fake.transport(), base_url="http://x")
    plain = http.get("/api/v1/functions/export").json()
    assert all("valves" not in entry for entry in plain)
    with_valves = http.get("/api/v1/functions/export", params={"include_valves": "true"}).json()
    assert {e["id"]: e["valves"] for e in with_valves}["pii_mask"]["api_key"] == "dummy-not-secret"
    recorded = fixture("function_export_with_valves")[1][0]["valves"]
    assert recorded["api_key"] == "dummy-not-secret"  # the recording planted the same dummy value


def test_auth_and_unknown_routes():
    fake = FakeOpenWebUI(token="right")
    http = httpx.Client(transport=fake.transport(), base_url="http://x")
    assert http.get("/api/v1/tools/export").status_code == 401
    assert http.get("/api/v1/tools/export", headers={"Authorization": "Bearer right"}).status_code == 200
    assert http.get("/api/v1/nope", headers={"Authorization": "Bearer right"}).status_code == 404


def test_state_file_roundtrip(tmp_path):
    state = tmp_path / "state.json"
    first = FakeOpenWebUI(state_path=state)
    assert not state.exists()  # reading never creates the file
    with client_for(first) as c:
        c.toggle("function", "pii_mask")
    assert state.is_file()
    second = FakeOpenWebUI(state_path=state)
    assert second.items["function"]["pii_mask"]["is_active"] is True
