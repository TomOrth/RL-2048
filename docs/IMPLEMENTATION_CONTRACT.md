# Worker contract

Read PLAN.md and backend/app/contracts.py / frontend/src/api/types.ts. Parent owns those files and root/frontend build configuration. Workers own their assigned files, and may request contract additions.

## SessionStore (engine worker implements)

Synchronous methods, each mutation/read safely locked per session; raises GameError(status_code, code, message), whose attributes the API/connector can use:

- create(seed: int | None = None, mode: ControlMode = 'human') -> CreateGameResponse
- state(game_id: str) -> GameState (detached snapshot)
- move(game_id: str, request: MoveRequest) -> MoveResult
- control(game_id: str, request: ControlRequest) -> GameState
- history(game_id: str) -> dict matching frontend GameHistory

One store instance is created by create_app() in main.py and available at app.state.store. create_app(store=None) supports test isolation. Error JSON: {"error": {"code": "stale_revision", "message": "..."}}. API endpoints and history schema follow PLAN and shared types. POST /api/games returns {state,seed}, GET returns state only. Backend game routes must be async so the parent can add an awaited controller-change hook; never hold locks across awaits. Engine worker initially creates only game routes, app static serving and /api/health.

## LLMManager (connector worker implements)

backend/app/llm/router.py provides create_llm_router(store) -> (APIRouter, manager). Parent registers it in main.py. manager.on_control_change(game_id) and manager.shutdown() are async. Hook is called after PUT control; cancels inference/run jobs to prevent late writes. Manager additionally rechecks revision/source/paused under store mutation lock. LLM-only operations do not need an engine-specific hook; manager owns their cancellation.

Endpoints per game:

- GET /api/games/{id}/llm/settings -> LLMSettingsResponse, or 404 llm_not_configured
- PUT /api/games/{id}/llm/settings -> LLMSettingsResponse, accepts LLMSettingsRequest
- GET /api/games/{id}/llm/status -> LLMStatus
- POST /api/games/{id}/llm/check -> LLMCheckResponse; no board mutation
- POST /api/games/{id}/llm/step -> MoveResult; require builtin mode, can be paused
- POST /api/games/{id}/llm/run -> LLMStatus; require builtin mode, resumes paused control through store.control and starts background loop
- POST /api/games/{id}/llm/pause -> LLMStatus; cancels task and sets builtin paused via store.control, ensuring revision invalidation

Run/step payloads are empty. Reject overlapping jobs with 409 llm_busy. Step temporarily resumes if paused (increments revision) and restores paused after successful step, returning current final state. Failed inference pauses builtin mode and updates status.error. Changing settings cancels outstanding jobs and invalidates their revision. Any key serialization/logging must redact keys, including upstream errors. Use httpx AsyncClient with injectable transport/client factory for tests. No external LLM requests during build/testing unless the user supplies an endpoint.

## Frontend

Implement fetch helpers in frontend/src/api/client.ts using above contracts; all endpoints relative to /api. Parent owns types.ts. Existing games can be opened by ?game=<id>. Fetch history for seed when attaching. New game POST state envelope differs from GET state. Persist only selected game ID, not model credentials. Model settings editable in UI; blank password means preserve existing key (send null); explicit clear-key action sends empty string. Settings remain backend-only and per game. Use fixtures while other workers build; never ship fake data fallback.
