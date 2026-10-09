# 2048 web app implementation plan

## Scope

Build a local web app where a human can play 2048, an external LLM harness can control the same game through HTTP, and a human can watch or take over an automated game. A small built-in model connector is a second milestone.

The app supplies game rules, state, controls, and move history. Fine-tuning, dataset generation, RL training, benchmark orchestration, and cloud model deployment are outside this plan.

This document records the implementation contract. Three GPT 6 Luna workers implemented the engine/API, frontend, and model connector; the parent integrated them. See README.md for startup instructions.

## Stack and structure

- Backend: Python, FastAPI, a pure Python game engine, and pytest for rules/API verification.
- Frontend: React, TypeScript, Vite, and CSS. Keep dependencies small.
- Development: Vite proxies `/api` to FastAPI; both listen on localhost.
- Local production: FastAPI serves the frontend build and API from one origin.
- Storage: in-memory game sessions initially, with downloadable JSON history. Server restarts discard sessions; document this and handle unavailable games in the UI. Add durable storage only if needed later.
- Live updates: poll the selected game while the page is visible. Start with a modest interval, such as 300 ms; avoid overlapping requests and ignore responses older than the displayed revision. WebSockets are unnecessary for the first version.

Proposed ownership:

```text
backend/app/contracts.py       shared Python models
backend/app/engine.py          game rules and seeded spawning
backend/app/sessions.py        session state, locking, history
backend/app/main.py            API and static-file serving
backend/app/llm/               optional built-in connector
backend/tests/                engine, API, connector tests
frontend/src/api/              generated types and request helpers
frontend/src/components/       board, controls, inspector
frontend/src/App.tsx           selected game and UI state
examples/play_via_api.py       external-controller example
docs/api.md                   HTTP examples and behavior
```

## Game behavior

Use a 4×4 board with actual tile values and zero for empty cells. Rows run top to bottom, columns left to right.

- Start with two random tiles.
- Spawn a 2 with probability 0.9 or a 4 with probability 0.1 in a uniformly selected empty cell.
- Slide and merge in the selected direction; a newly merged tile cannot merge again in that move.
- Add the values of newly merged tiles to the score.
- Spawn one tile only after a move changes the board.
- A direction that leaves the board unchanged is a no-op: no score change, spawn, or RNG advancement.
- Set `reached_2048` when a tile reaches at least 2048; keep playing until there are no legal moves.
- Use a session-local seeded RNG. Legal-move inspection and UI reads must never consume randomness.

These rules follow the [original 2048 implementation](https://github.com/gabrielecirulli/2048/blob/master/js/game_manager.js), with automatic continuation beyond 2048 as our explicit app behavior.

Restart creates a new game ID. Users can reuse a seed or request a new one. Moves are allowed only for an ongoing game.

## Shared API contract

Every game state contains:

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

`status` is `ongoing` or `game_over`; `control.mode` is `human`, `external`, or, in milestone two, `builtin`. Legal moves always use the order shown above, filtering out no-ops.

| Endpoint | Request | Result |
| --- | --- | --- |
| `POST /api/games` | Optional integer `seed`; initial control mode, default `human` | New game state; return the chosen seed separately as session metadata |
| `GET /api/games/{id}` | None | Current game state |
| `POST /api/games/{id}/moves` | `direction`, `expected_revision`, `source` (`human`, `external`, `builtin`) | Move result and current game state |
| `PUT /api/games/{id}/control` | `mode`, `paused`, `expected_revision` | Updated game state |
| `GET /api/games/{id}/history` | None | Versioned JSON export including seed, initial board, moves, and final state |

The public observation is the state above; seed and RNG internals are not included in model prompts. External harnesses can consume JSON directly without parsing the visual board.

A move result contains `state`, `moved`, `score_delta`, and optional `spawned_tile` with row, column, and value. A valid-direction no-op returns success with `moved: false`. Invalid direction strings fail validation. Stale revisions, wrong control sources, paused automation, and moves after game over return explicit conflict errors with stable error codes. Missing games return 404.

Serialize mutations with a per-game lock. Increment revision for board changes and actual control changes. Check revision and controller mode under that same lock. Taking over switches to human control and increments revision, invalidating already pending automation moves. `source` expresses controller ownership in this local app; it is not an authentication mechanism.

History records timestamps, source, direction, boards before/after, score delta, spawn, and revisions. Include valid-direction no-ops. Refused commands return errors and do not become completed game moves. JSON exports contain no credentials.

## Interface

Visual thesis: a calm, warm game surface with a large board, crisp tile numbers, restrained controls, and a compact inspector.

Content plan:

1. Main workspace: board, score, highest tile, and new-game control.
2. Human controls: arrow keys, WASD, swipe gestures, and accessible on-screen direction buttons.
3. Controller controls: Human / External; pause and take over for external play.
4. Inspector: game ID, seed, legal moves, and recent move history. Make the ID and API URL easy to copy and provide JSON export.
5. Model settings and built-in run controls appear with milestone two.

Desktop places the inspector beside the board. Mobile places it below. Avoid marketing copy, decorative imagery, and dashboard card grids; the board is the visual anchor.

Interaction thesis: short directional tile movement, a subtle merge pulse, and a clear controller-status transition. Respect reduced-motion preferences. Preserve authoritative server state while animations run; intermediate display frames never become game state.

Keyboard handling must not intercept typing in fields. Disable human move controls in automated mode and show the reason. Network errors retain the last board and show a recoverable message. An expired game offers a new game. A 2048 milestone is non-blocking; game over offers restart. Swipes should not prevent ordinary scrolling outside the board.

The board renderer uses backend transitions/spawn metadata to animate. It does not implement an independent game engine.

## Built-in OpenAI-compatible LLM connection: milestone two

The connector targets the **OpenAI-compatible Chat Completions HTTP API**. A user supplies their local or remote model server URL and the exact served model name. The backend sends prompts using that API's request format and reads its response format. This is a convenience controller using the same session and move validation as the external HTTP path.

- Configure server URL, model name, optional API key, response token limit, token-limit field, and request timeout.
- Store credentials on the backend, preferably through environment variables; do not return them to the browser or include them in exports/logs.
- Show a simple connection check and concise error messages.
- Send the current board, legal moves, and a short instruction to return exactly `up`, `down`, `left`, or `right`.
- Trim surrounding whitespace and normalize letter case; reject prose, ambiguous output, empty responses, and no-op choices. No silent replacement with a different move.
- Support One move, Run, and Pause. Keep only one model request in flight per game; allow a delay between successful moves.
- Pause on malformed output, an illegal move, or a connection failure, showing the cause. Stop at game over.
- Capture the observed revision before inference; recheck revision, controller mode, and pause status before applying the result. Discard stale responses.
- Pausing or taking over must prevent a late response from applying. Clean up tasks when games are removed or the server shuts down.

The external-controller path works without this connector and without any model server. Provider-specific reasoning flags and structured-output extensions can be added only when the configured server needs them.

### URL handling and transport

Accept an absolute HTTP or HTTPS URL. Resolve the completion endpoint deterministically, preserving custom path prefixes and removing trailing slashes:

| Configured URL | POST target |
| --- | --- |
| `http://localhost:8000` | `http://localhost:8000/v1/chat/completions` |
| `http://localhost:8000/v1` | `http://localhost:8000/v1/chat/completions` |
| `https://models.example.com/proxy/v1/` | `https://models.example.com/proxy/v1/chat/completions` |
| `https://models.example.com/v1/chat/completions` | Use the supplied endpoint unchanged |

For another non-root base path, append `/chat/completions` to that path; do not silently add `/v1`. Show the resolved URL in settings so users can check it. Reject URL credentials, query strings, and fragments; the API key has its own field.

Use backend `httpx` requests, with `Content-Type: application/json` and `Authorization: Bearer <api_key>` when a key is provided. Omit authorization when no key is configured, allowing unauthenticated local servers. All inference calls originate from the backend, including connection checks.

### Request and response contract

Send a non-streaming JSON request using the configured model name. Example application request:

```json
{
  "model": "configured-model-name",
  "messages": [
    {
      "role": "system",
      "content": "Play 2048. Choose one of the provided legal moves. Reply with exactly one word: up, down, left, or right."
    },
    {
      "role": "user",
      "content": "Board (rows top to bottom; 0 means empty):\n0 2 0 0\n0 0 0 0\n0 0 4 0\n0 0 0 0\nLegal moves: up, down, left, right"
    }
  ],
  "stream": false,
  "max_completion_tokens": 64
}
```

Use a fresh board prompt each turn. The app does not send the entire game transcript. Omit optional sampling parameters by default; add them only when supported by the configured model.

Default to `max_completion_tokens`. Offer an explicit legacy compatibility setting that sends `max_tokens` instead, never both. OpenAI documents `max_tokens` as deprecated; third-party servers can implement different subsets, so the selected field is a configurable compatibility choice. A reasoning model may require a larger completion budget or explicit server-specific reasoning settings.

Parse the action exclusively from the first choice's `message.content`, for example:

```json
{
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "left"},
      "finish_reason": "stop"
    }
  ]
}
```

Require a nonempty `choices` array and string content; apply the action validation above. Pause on refusal, tool calls, truncated output (`finish_reason: "length"`), malformed JSON, or an unexpected response shape. Token usage is optional metadata when provided. Do not require streaming, function calling, structured output, or a model-list endpoint.

Connection checks send a small completion request through this exact path and validate the returned schema without applying a game move. Report HTTP authentication, missing-route/model, rate-limit, timeout, and server errors clearly, with secrets redacted. Do not retry failed requests automatically in the initial connector.

The wire format is based on the [official OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create). URL normalization and compatibility settings above are our app's design decisions. Compatibility is verified against a mock server implementing this contract, then smoke-tested against the user's configured server.

## Verification and completion criteria

Rules tests cover all directions, gaps, score updates, and tricky merges: `[2,2,2,2]` becomes `[4,4,0,0]` with score delta 8 when moved left; `[2,2,4,0]` becomes `[4,4,0,0]`, without a second merge. Test legal moves, full-board terminal detection, no-op RNG preservation, and seeded replay.

API checks cover independent games, stale requests, simultaneous moves, controller switches, pause, missing games, and exported history. A Python example should create an external game, choose a random legal move repeatedly, and finish or stop at a configurable move limit while the browser displays the same board.

Browser verification focuses on desktop play, typing in settings fields, watching external play, takeover, model control, and server errors. The user requested that mobile testing be skipped. Verify the production build served by FastAPI.

Connector tests use a mock OpenAI-compatible HTTP model server to assert resolved URL, POST method, headers, model name, messages, `stream: false`, selected token-limit field, and `choices[0].message.content` parsing. Cover successful moves, malformed output, HTTP errors, timeouts, and delayed responses after pause/takeover. A real model smoke test runs only when an endpoint is available; absence of credentials must not block the app's main acceptance checks.

Milestone one is complete when a human can play, a script can control a separate or watched game through the documented API, takeover is safe, and histories can be exported. Milestone two is complete when a configured model can run/step/pause through the same engine and failures are visible.

## Delegation sequence for GPT 6 Luna

Use three workers at a time, with the parent agent owning shared contracts and integration. Do not start workers until the user requests delegation.

Before parallel work, the parent creates the skeleton, shared Python contracts, example responses, frontend API types, and development commands. Freeze the contract above so workers can use fixtures immediately. Only the parent changes shared configuration/contracts, incorporating worker requests as needed.

| Worker | Owned work | Handoff |
| --- | --- | --- |
| Engine/API | Engine, sessions, HTTP routes, related tests | Running API, seeded games, safe controller transitions, history export |
| Frontend | Frontend components, styling, input, polling, inspector | Playable responsive UI using shared fixtures first, then the real API |
| Integration/connector | External Python example and API docs first; OpenAI-compatible Chat Completions connector and contract tests second | Demonstrated script control, then model autoplay using the configured server URL/model |

Worker three begins with the mock external client while the engine and UI are built. The connector starts once the real session interface is available. The parent integrates routes/UI settings, runs end-to-end checks, and fixes cross-component behavior. Workers report changed files, how they verified their work, and remaining issues.

Implementation order: shared contract → parallel engine/UI/external client → milestone-one integration → model connector → final verification and startup instructions. No publishing or model deployment is part of this sequence.
