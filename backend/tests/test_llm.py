from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from app.contracts import LLMSettingsRequest
from app.llm.router import LLMManager, _response_format, create_llm_router, resolve_completion_url
from app.main import create_app
from app.sessions import SessionStore


def make_store(seed: int = 10) -> tuple[SessionStore, str]:
    store = SessionStore()
    game_id = store.create(seed=seed, mode="builtin").state.id
    return store, game_id


def config(manager: LLMManager, game_id: str, **kwargs):
    defaults = {"url": "http://model.test/v1", "model": "test-model", "api_key": None}
    defaults.update(kwargs)
    return manager.put_settings(game_id, LLMSettingsRequest(**defaults))


def mock_client(handler):
    transport = httpx.MockTransport(handler)
    return lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs)


@pytest.mark.parametrize(("upstream_status", "body", "expected_error"), [
    (400, {"error": {"message": "private-upstream-body test-secret"}}, "Model server rejected the request (HTTP 400); it may not support the requested JSON Schema or another request parameter"),
    (200, {"choices": [{"message": {"content": "private-upstream-body test-secret"}, "finish_reason": "stop"}]}, "Model response must be a JSON object with one legal direction field"),
    (200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {"completion_tokens": 64, "completion_tokens_details": {"reasoning_tokens": 64}}}, "Model response was truncated by the token limit (64). Increase Token limit, save settings, and try again."),
])
def test_check_logs_502_cause_without_credentials_or_raw_body(caplog, upstream_status, body, expected_error):
    store, game_id = make_store()
    app = create_app(store)
    manager = app.state.llm_manager
    manager.client_factory = mock_client(lambda _: httpx.Response(upstream_status, json=body))
    config(manager, game_id, api_key="test-secret")
    caplog.set_level(logging.INFO, logger="app.llm.router")

    with TestClient(app) as client:
        response = client.post(f"/api/games/{game_id}/llm/check")

    assert response.status_code == 502
    assert response.json()["error"]["message"] == expected_error
    assert "LLM check started" in caplog.text
    assert "endpoint=http://model.test/v1/chat/completions" in caplog.text
    assert f"status={upstream_status}" in caplog.text
    assert f"LLM check failed game={game_id}: {expected_error}" in caplog.text
    assert "test-secret" not in caplog.text
    assert "private-upstream-body" not in caplog.text
    if "usage" in body:
        assert "completion_tokens=64 reasoning_tokens=64" in caplog.text
        assert "finish_reason=length" in caplog.text


@pytest.mark.parametrize(("source", "expected"), [
    ("http://localhost:8000", "http://localhost:8000/v1/chat/completions"),
    ("http://localhost:8000/v1/", "http://localhost:8000/v1/chat/completions"),
    ("https://models.example.com/proxy/v1/", "https://models.example.com/proxy/v1/chat/completions"),
    ("https://models.example.com/v1/chat/completions", "https://models.example.com/v1/chat/completions"),
    ("https://models.example.com/proxy/custom/chat/completions", "https://models.example.com/proxy/custom/chat/completions"),
    ("https://models.example.com/proxy", "https://models.example.com/proxy/chat/completions"),
])
def test_resolve_completion_url(source, expected):
    assert resolve_completion_url(source) == expected


@pytest.mark.parametrize("url", [
    "ftp://model.test", "model.test", "http://user:pass@model.test", "http://model.test?key=x", "http://model.test/#frag", "http://model.test:bad",
])
def test_rejects_unsafe_or_unsupported_url(url):
    with pytest.raises(ValueError):
        resolve_completion_url(url)


@pytest.mark.asyncio
async def test_wire_contract_and_action_parse():
    store, game_id = make_store()
    initial = store.state(game_id)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{
            "index": 0, "message": {"role": "assistant", "content": '{"direction":"left"}'}, "finish_reason": "stop"
        }]})

    manager = LLMManager(store, mock_client(handler))
    public = config(manager, game_id, api_key="test-secret")
    assert public.api_key_configured is True
    assert "api_key" not in public.model_dump()
    result = await manager.step(game_id)
    assert result.moved
    assert seen["method"] == "POST"
    assert seen["url"] == "http://model.test/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer test-secret"
    payload = seen["body"]
    assert payload["model"] == "test-model"
    assert payload["stream"] is False
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "2048_move", "strict": True,
            "schema": {
                "additionalProperties": False,
                "properties": {"direction": {"enum": list(initial.legal_moves), "title": "Direction", "type": "string"}},
                "required": ["direction"], "title": "_MoveResponse", "type": "object",
            },
        },
    }
    assert payload["max_completion_tokens"] == 64
    assert "max_tokens" not in payload
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    rows = "\n".join(" ".join(str(value) for value in row) for row in initial.board)
    assert payload["messages"][1]["content"] == (
        "Board (rows top to bottom; columns left to right; 0 means empty):\n"
        f"{rows}\nLegal moves: {', '.join(initial.legal_moves)}"
    )
    assert manager.status(game_id).last_action == "left"


@pytest.mark.asyncio
async def test_legacy_limit_field_and_no_auth_when_key_absent():
    store, game_id = make_store()
    state = store.state(game_id)
    action = state.legal_moves[0]
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"direction": action})}, "finish_reason": "stop"}]})

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id, token_limit_field="max_tokens", max_tokens=91)
    await manager.step(game_id)
    assert seen["max_tokens"] == 91
    assert "max_completion_tokens" not in seen
    assert seen["authorization"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {"choices": []},
    {"choices": [{"message": {"content": "left because it seems best"}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": '{"direction":"left","extra":true}'}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": '{"direction":7}'}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": '{"direction":"north"}'}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": '{"action":"left"}'}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": '{"direction":"left"}'}, "finish_reason": "length"}]},
    {"choices": [{"message": {"content": '{"direction":"left"}'}, "finish_reason": "content_filter"}]},
    {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
    {"choices": [{"message": {"content": '{"direction":"left"}', "tool_calls": [{"id": "x"}]}, "finish_reason": "tool_calls"}]},
    {"choices": [{"message": {"content": '{"direction":"left"}', "refusal": "can\'t"}, "finish_reason": "stop"}]},
])
async def test_malformed_response_pauses_and_sets_error(response):
    store, game_id = make_store()

    def handler(_request):
        return httpx.Response(200, json=response)

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id)
    with pytest.raises(Exception):
        await manager.step(game_id)
    assert store.state(game_id).control.paused
    assert manager.status(game_id).error


@pytest.mark.asyncio
async def test_http_error_message_does_not_leak_key_or_upstream_body():
    store, game_id = make_store()

    def handler(_request):
        return httpx.Response(401, text="invalid test-secret Bearer test-secret")

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id, api_key="test-secret")
    with pytest.raises(Exception) as caught:
        await manager.step(game_id)
    message = str(caught.value)
    assert "test-secret" not in message
    assert "invalid" not in message
    assert manager.status(game_id).error == "Model server rejected authentication (HTTP 401)"


@pytest.mark.asyncio
async def test_timeout_is_reported_without_retry():
    store, game_id = make_store()
    calls = 0

    async def handler(_request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("upstream details")

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id)
    with pytest.raises(Exception) as caught:
        await manager.step(game_id)
    assert "timed out" in str(caught.value)
    assert calls == 1


@pytest.mark.asyncio
async def test_connection_check_validates_response_without_mutating_game():
    store, game_id = make_store()
    before = store.state(game_id)
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{
            "message": {"content": json.dumps({"direction": before.legal_moves[0]})}, "finish_reason": "stop"
        }]})

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id)
    checked = await manager.check(game_id)
    assert checked.ok
    assert checked.content == json.dumps({"direction": before.legal_moves[0]}, separators=(",", ":"))
    prompt = seen["messages"][1]["content"]
    board_rows = "\n".join(" ".join(str(value) for value in row) for row in before.board)
    assert f"\n{board_rows}\nLegal moves: {', '.join(before.legal_moves)}" in prompt
    assert seen["response_format"]["json_schema"]["schema"]["properties"]["direction"]["enum"] == before.legal_moves
    after = store.state(game_id)
    assert after.board == before.board
    assert after.revision == before.revision


@pytest.mark.asyncio
async def test_connection_check_uses_representative_board_for_game_over_session():
    store, game_id = make_store()
    terminal_board = [
        [2, 4, 2, 4],
        [4, 2, 4, 2],
        [2, 4, 2, 4],
        [4, 2, 4, 2],
    ]
    store._sessions[game_id].board = [row[:] for row in terminal_board]
    before = store.state(game_id)
    assert before.status == "game_over"
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{
            "message": {"content": '{"direction":"left"}'}, "finish_reason": "stop"
        }]})

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id)
    checked = await manager.check(game_id)

    probe = [[0] * 4 for _ in range(4)]
    probe[1][1] = 2
    expected_legal = ["up", "down", "left", "right"]
    probe_text = "\n".join(" ".join(str(value) for value in row) for row in probe)
    assert checked.ok
    assert checked.content == '{"direction":"left"}'
    assert f"\n{probe_text}\nLegal moves: {', '.join(expected_legal)}" in seen["messages"][1]["content"]
    assert seen["response_format"]["json_schema"]["schema"]["properties"]["direction"]["enum"] == expected_legal
    assert store.state(game_id) == before


def test_response_schema_is_fresh_and_limits_single_legal_move():
    only_left = _response_format(["left"])
    assert only_left["json_schema"]["strict"] is True
    schema = only_left["json_schema"]["schema"]
    assert schema["required"] == ["direction"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["direction"]["enum"] == ["left"]
    assert _response_format(["up", "right"])["json_schema"]["schema"]["properties"]["direction"]["enum"] == ["up", "right"]


@pytest.mark.asyncio
async def test_valid_but_illegal_direction_is_rejected():
    store, game_id = make_store()
    manager = LLMManager(store, mock_client(lambda _request: httpx.Response(200, json={
        "choices": [{"message": {"content": '{"direction":"right"}'}, "finish_reason": "stop"}]
    })))
    config(manager, game_id)
    settings = manager.settings[game_id]
    with pytest.raises(Exception, match="illegal move"):
        await manager._complete(settings, [[0] * 4 for _ in range(4)], ["left"])


@pytest.mark.asyncio
async def test_run_applies_valid_json_move_and_records_response():
    store, game_id = make_store()
    state = store.state(game_id)
    started = asyncio.Event()
    action = state.legal_moves[0]

    async def handler(_request):
        started.set()
        return httpx.Response(200, json={"choices": [{
            "message": {"content": json.dumps({"direction": action})}, "finish_reason": "stop"
        }]})

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id, delay_seconds=60)
    await manager.start_run(game_id)
    await started.wait()
    for _ in range(100):
        if store.state(game_id).move_count == 1:
            break
        await asyncio.sleep(0.001)
    assert store.state(game_id).move_count == 1
    assert manager.status(game_id).last_action == action
    assert manager.status(game_id).last_response == json.dumps({"direction": action}, separators=(",", ":"))
    await manager.pause(game_id)


@pytest.mark.asyncio
async def test_settings_change_cancels_pending_step_before_it_can_mutate_board():
    store, game_id = make_store()
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"direction":"left"}'}, "finish_reason": "stop"}]})

    manager = LLMManager(store, mock_client(handler))
    config(manager, game_id)
    before = store.state(game_id)
    pending = asyncio.create_task(manager.step(game_id))
    await started.wait()
    await manager._invalidate(game_id)
    config(manager, game_id, model="replacement")
    with pytest.raises(Exception) as caught:
        await pending
    assert "discarded" in str(caught.value)
    after = store.state(game_id)
    assert after.board == before.board
    assert after.move_count == before.move_count


@pytest.mark.asyncio
async def test_control_takeover_route_discards_delayed_step_response():
    app = create_app()
    manager = app.state.llm_manager
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"direction":"left"}'}, "finish_reason": "stop"}]})

    manager.client_factory = mock_client(handler)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = (await client.post("/api/games", json={"mode": "builtin", "seed": 10})).json()
        game_id = created["state"]["id"]
        await client.put(f"/api/games/{game_id}/llm/settings", json={
            "url": "http://model.test/v1", "model": "test-model"
        })
        pending = asyncio.create_task(client.post(f"/api/games/{game_id}/llm/step"))
        await started.wait()
        control = await client.put(f"/api/games/{game_id}/control", json={
            "mode": "human", "paused": False, "expected_revision": created["state"]["revision"]
        })
        assert control.status_code == 200
        discarded = await pending
        assert discarded.status_code == 409
        assert discarded.json()["error"]["code"] == "llm_response_discarded"
        final_state = (await client.get(f"/api/games/{game_id}")).json()
        assert final_state["control"]["mode"] == "human"
        assert final_state["move_count"] == 0
        assert manager.status(game_id).busy is False
    release.set()


@pytest.mark.asyncio
async def test_pause_route_cancels_background_run_and_clears_busy_status():
    app = create_app()
    manager = app.state.llm_manager
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(_request):
        started.set()
        await release.wait()
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"direction":"left"}'}, "finish_reason": "stop"}]})

    manager.client_factory = mock_client(handler)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        game = (await client.post("/api/games", json={"mode": "builtin", "seed": 10})).json()["state"]
        game_id = game["id"]
        await client.put(f"/api/games/{game_id}/llm/settings", json={
            "url": "http://model.test/v1", "model": "test-model", "delay_seconds": 0
        })
        run_response = await client.post(f"/api/games/{game_id}/llm/run")
        assert run_response.json()["running"] is True
        assert run_response.json()["busy"] is True
        await started.wait()
        paused = await client.post(f"/api/games/{game_id}/llm/pause")
        assert paused.status_code == 200
        assert paused.json()["running"] is False
        assert paused.json()["busy"] is False
        final_state = (await client.get(f"/api/games/{game_id}")).json()
        assert final_state["control"]["paused"] is True
        assert final_state["move_count"] == 0
    release.set()


def test_api_registers_routes_and_settings_never_return_secret():
    app = create_app()
    client = TestClient(app)
    game = client.post("/api/games", json={"mode": "builtin", "seed": 2}).json()["state"]
    response = client.put(f"/api/games/{game['id']}/llm/settings", json={
        "url": "http://127.0.0.1:8001/v1", "model": "local", "api_key": "hidden-value"
    })
    assert response.status_code == 200
    assert response.json()["api_key_configured"]
    assert "hidden-value" not in response.text
