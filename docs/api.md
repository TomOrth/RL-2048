# HTTP API

The FastAPI server exposes the game state as JSON, so scripts can play without reading the browser. Start a game with `POST /api/games`, read the state with `GET /api/games/{id}`, make a move with `POST /api/games/{id}/moves`, change its controller with `PUT /api/games/{id}/control`, and download its history with `GET /api/games/{id}/history`.

## External controller example

Run the server at `http://127.0.0.1:8000`, then use the standard-library example:

```sh
python examples/play_via_api.py --max-steps 100 --delay 0.2
```

It creates a game in `external` mode, chooses uniformly from each returned `legal_moves` list, and submits the state's `revision` with every move. The browser can open the same game ID to watch or take control. Use `--game-id ID` to play an existing externally controlled game, `--seed N` to make the initial board reproducible, and `--seed-rng N` to make the script's choices reproducible. `--max-steps` bounds play even when the board does not end.

## Game routes

### `POST /api/games`

Request fields: optional integer `seed`; optional `mode` (`human`, `external`, or `builtin`, default `human`). Returns `{ "state": <GameState>, "seed": number }`.

### `GET /api/games/{id}`

Returns the current `GameState`:

```json
{
  "id": "game-id",
  "revision": 0,
  "board": [[0, 2, 0, 0], [0, 0, 0, 0], [0, 0, 4, 0], [0, 0, 0, 0]],
  "score": 0,
  "max_tile": 4,
  "legal_moves": ["up", "down", "left", "right"],
  "status": "ongoing",
  "reached_2048": false,
  "move_count": 0,
  "control": {"mode": "human", "paused": false}
}
```

`legal_moves` excludes directions that would leave the board unchanged. `revision` increments on board changes and actual control changes.

### `POST /api/games/{id}/moves`

Provide `direction`, `expected_revision`, and `source` (`human`, `external`, or `builtin`). The source must match the current controller; automated sources also require an unpaused game. A valid direction that changes nothing succeeds with `moved: false` and does not spawn a tile. A changed board spawns exactly one tile. The response contains `state`, `moved`, `score_delta`, optional `spawned_tile`, and tile `transitions`.

```sh
curl -X POST http://127.0.0.1:8000/api/games/GAME_ID/moves \
  -H 'Content-Type: application/json' \
  -d '{"direction":"left","expected_revision":0,"source":"external"}'
```

### `PUT /api/games/{id}/control`

Provide `mode`, `paused`, and `expected_revision`. Switching to `human` takes control and invalidates pending model responses. Pause is meaningful for automated modes.

### `GET /api/games/{id}/history`

Returns versioned JSON history with the seed, initial board, completed move records, and final state. Credentials are never part of game history.

Missing games return 404. A stale revision, wrong controller, paused automation, or a game-over move returns a conflict with a stable error code. Sessions and their histories are held in memory and disappear when the server restarts.

## Built-in model controller

The built-in controller sends non-streaming OpenAI-compatible Chat Completions requests from the backend. Each request includes a strict JSON Schema `response_format` whose `direction` enum contains only the current board's legal moves. The assistant content must be a JSON object such as `{"direction":"left"}`; the backend validates it before applying the move and records that JSON in status. Check sends the current board and legal moves without changing the game; for a completed game, it sends a separate representative board so the endpoint can still be checked. Configure the controller per game with `PUT /api/games/{id}/llm/settings`:

```json
{
  "url": "http://localhost:8001/v1",
  "model": "served-model-name",
  "api_key": null,
  "max_tokens": 64,
  "token_limit_field": "max_completion_tokens",
  "timeout_seconds": 30,
  "delay_seconds": 0.4
}
```

`api_key: null` preserves a key already stored for that game; an empty string clears it. The response includes the normalized `resolved_url` and `api_key_configured`, never the key itself. URLs must be absolute HTTP or HTTPS URLs without embedded credentials, query strings, or fragments. A root URL resolves to `/v1/chat/completions`; `/v1` and custom path prefixes are preserved. A URL already ending in `/v1/chat/completions` is used unchanged. `max_completion_tokens` is the default token budget field; choose `max_tokens` only for servers that require the older field. Exactly one is sent.

The game must be created or switched to `builtin` mode before using step or run. A step performs one inference and one legal move; if the game was paused, it pauses again after a successful move. Run resumes paused control and continues with the configured delay. Pause cancels pending work and increments the game's control revision. Malformed, refused, truncated, illegal, or failed responses pause the game and set a concise status error. There is no automatic retry or random fallback.

| Method and path | Behavior |
| --- | --- |
| `GET /api/games/{id}/llm/settings` | Get settings without the API key; 404 `llm_not_configured` if unset |
| `PUT /api/games/{id}/llm/settings` | Set URL, model, optional key, token limit, timeout, and run delay |
| `GET /api/games/{id}/llm/status` | Get configured/running/busy state and last result or error |
| `POST /api/games/{id}/llm/check` | Send a small test completion and validate its response; no game move |
| `POST /api/games/{id}/llm/step` | Perform one model move; request body is empty |
| `POST /api/games/{id}/llm/run` | Resume and start background moves; request body is empty |
| `POST /api/games/{id}/llm/pause` | Cancel model work and pause builtin control |

The server must support OpenAI-compatible Chat Completions `response_format` with `type: "json_schema"`; vLLM documents the feature in its [structured outputs guide](https://docs.vllm.ai/en/stable/features/structured_outputs/). Compatibility depends on the deployed server version and model backend. HTTP 400/422 errors report a generic hint that the schema or another request parameter may be unsupported, without exposing the upstream body. The backend still validates responses locally if a server ignores schema constraints.

Only one model request can be active per game. These routes require the backend's configured HTTP client and do not require a provider-specific SDK. Settings, including credentials, are held in process memory and disappear on restart.
