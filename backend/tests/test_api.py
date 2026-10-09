from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.sessions import GameError, MAX_SAFE_SEED, SessionStore


def client_and_game(mode="human", seed=4):
    client = TestClient(create_app(SessionStore()))
    created = client.post("/api/games", json={"seed": seed, "mode": mode})
    assert created.status_code == 200
    return client, created.json()


def test_health_create_get_and_unknown_api_route():
    client, created = client_and_game()
    assert client.get("/api/health").json() == {"status": "ok"}
    game_id = created["state"]["id"]
    assert client.get(f"/api/games/{game_id}").json() == created["state"]
    assert client.get("/api/not-a-route").status_code == 404
    missing = client.get("/api/games/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "game_not_found"


def test_stale_revision_pause_and_takeover_invalidate_automation():
    client, created = client_and_game(mode="external")
    state = created["state"]
    game_id = state["id"]
    paused = client.put(f"/api/games/{game_id}/control", json={
        "mode": "external", "paused": True, "expected_revision": state["revision"],
    }).json()
    result = client.post(f"/api/games/{game_id}/moves", json={
        "direction": "left", "expected_revision": paused["revision"], "source": "external",
    })
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "paused"

    human = client.put(f"/api/games/{game_id}/control", json={
        "mode": "human", "paused": False, "expected_revision": paused["revision"],
    }).json()
    stale = client.post(f"/api/games/{game_id}/moves", json={
        "direction": "left", "expected_revision": paused["revision"], "source": "external",
    })
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_revision"
    wrong_owner = client.post(f"/api/games/{game_id}/moves", json={
        "direction": "left", "expected_revision": human["revision"], "source": "external",
    })
    assert wrong_owner.status_code == 409
    assert wrong_owner.json()["error"]["code"] == "wrong_controller"


def test_successful_move_and_history_export_include_noops():
    client, created = client_and_game(seed=11)
    game_id = created["state"]["id"]
    initial = created["state"]
    no_op = next(direction for direction in ("up", "down", "left", "right") if direction not in initial["legal_moves"])
    no_op_result = client.post(f"/api/games/{game_id}/moves", json={
        "direction": no_op, "expected_revision": initial["revision"], "source": "human",
    })
    assert no_op_result.status_code == 200
    assert no_op_result.json()["moved"] is False
    assert no_op_result.json()["state"]["revision"] == initial["revision"]

    direction = initial["legal_moves"][0]
    moved = client.post(f"/api/games/{game_id}/moves", json={
        "direction": direction, "expected_revision": initial["revision"], "source": "human",
    })
    assert moved.status_code == 200
    result = moved.json()
    assert result["moved"] is True
    assert result["spawned_tile"] is not None
    assert result["state"]["revision"] == initial["revision"] + 1
    history = client.get(f"/api/games/{game_id}/history").json()
    assert history["schema_version"] == 1
    assert history["seed"] == 11
    assert history["initial_board"] == initial["board"]
    assert [move["moved"] for move in history["moves"]] == [False, True]
    assert history["final_state"] == result["state"]


def test_simultaneous_moves_serialize_revision_check_and_mutation():
    client, created = client_and_game(seed=7)
    state = created["state"]
    game_id = state["id"]
    direction = state["legal_moves"][0]
    payload = {"direction": direction, "expected_revision": state["revision"], "source": "human"}

    def submit():
        return client.post(f"/api/games/{game_id}/moves", json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    error = next(response for response in responses if response.status_code == 409)
    assert error.json()["error"]["code"] == "stale_revision"


def test_games_are_independent():
    client = TestClient(create_app(SessionStore()))
    a = client.post("/api/games", json={"seed": 1}).json()["state"]
    b = client.post("/api/games", json={"seed": 2}).json()["state"]
    assert a["id"] != b["id"]
    assert a["board"] != b["board"]
    changed = client.put(f"/api/games/{a['id']}/control", json={
        "mode": "external", "paused": False, "expected_revision": 0,
    }).json()
    assert changed["revision"] == 1
    assert client.get(f"/api/games/{b['id']}").json()["revision"] == 0


def test_generated_seed_is_javascript_safe_and_can_replay_initial_board():
    store = SessionStore()
    generated = store.create()
    assert 0 <= generated.seed < 2**53
    replay = store.create(seed=generated.seed)
    assert replay.state.board == generated.state.board


def test_store_rejects_seed_outside_javascript_safe_integer_range():
    with pytest.raises(GameError) as caught:
        SessionStore().create(seed=MAX_SAFE_SEED + 1)
    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_seed"

    with pytest.raises(GameError) as caught_negative:
        SessionStore().create(seed=-MAX_SAFE_SEED - 1)
    assert caught_negative.value.status_code == 422
    assert caught_negative.value.code == "invalid_seed"
