# RL-2048

Exploration into using RL and fine-tuning techniques to make an LLM play 2048.

A local 2048 web app for human play, external HTTP controllers, and an OpenAI-compatible LLM. The browser and model use one authoritative Python game engine.

The repository contains the game and model interface today. Future SFT, GRPO, and evaluation work belongs under `experiments/`; see [experiment organization](experiments/README.md). Training pipelines are not implemented yet.

## Start the app

Prerequisites: Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 20.19+ or 22.12+ with npm.

From this directory:

```sh
uv sync
npm ci --prefix frontend
npm run build --prefix frontend
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open [127.0.0.1:8000](http://127.0.0.1:8000). Start a game and use arrow keys, WASD, direction buttons, or swipe the board. Games continue past 2048 until no legal move remains.

For development, keep the backend running and use `npm run dev --prefix frontend`; Vite proxies API requests to port 8000. Rebuild the frontend and restart the backend when switching back to the single-server app.

## Connect an LLM

Start a game, enter the model server URL and exact served model name under **Model connection**, then save settings. Supply an API key only if your server requires one. **Check** makes a small inference request without moving the board. **One move** selects a single action; **Run model** plays until paused, game over, or an error. Human takeover discards any pending model response.

The connector sends OpenAI-compatible Chat Completions requests. Examples:

| URL entered | Request endpoint |
| --- | --- |
| `http://localhost:8001` | `http://localhost:8001/v1/chat/completions` |
| `http://localhost:8001/v1` | `http://localhost:8001/v1/chat/completions` |
| `https://api.openai.com/v1` | `https://api.openai.com/v1/chat/completions` |
| A full URL ending in `/chat/completions` | Used directly |

The backend posts `model`, `messages`, `stream: false`, the selected token-limit field, and an OpenAI-compatible strict `response_format` JSON Schema. The model must return `choices[0].message.content` as `{"direction":"left"}` with a direction legal for the current board. The schema's direction enum is limited to the current legal moves, and the backend validates the complete JSON response before applying a move. It sends optional authentication as `Authorization: Bearer <key>`.

The configured server must support `response_format.type: "json_schema"` for Chat Completions. vLLM documents this format in its [structured outputs guide](https://docs.vllm.ai/en/stable/features/structured_outputs/); support can depend on the deployed vLLM version, model, and decoding backend. A 400 or 422 response includes a safe hint that the schema or another request parameter may be unsupported. The backend does not fall back to unconstrained text.

Each inference receives a fixed system prompt describing the rules, random tile spawning, and the objective of maximizing final score while continuing beyond 2048. It suggests preserving space and mobility, preparing merges, and keeping large tiles ordered near a corner when practical. The user message contains only the current board and legal moves; previous moves are not included. The prompt is defined in `backend/app/llm/router.py`. These strategy suggestions have not been benchmarked against the original prompt; compare both on the same seeds and model settings before claiming a performance improvement.

**Modern** sends `max_completion_tokens`; **Legacy** sends `max_tokens`. Use the setting your server accepts. Output must fit the configured budget; reasoning models may need a higher limit or server configuration that disables reasoning. Unsupported output, connection errors, and illegal moves pause the controller with a visible error.

Credentials stay in backend memory. A blank key preserves the existing value; the explicit clear action removes it when settings are saved. A server restart discards games, history, model settings, and keys. Export a game's JSON history to keep it. The app runs on localhost and has no remote-user authentication.

Application logs appear in the backend terminal at INFO level alongside Uvicorn's server logs. LLM diagnostics include the endpoint, model, token budget, HTTP status, completion finish reason, and safe failure message. They omit authentication headers and raw upstream bodies. A 502 from `/llm/check` means the inference or response validation failed; read `error.message` in the response and the `app.llm.router` log entries for its cause. Backend code edits require a restart; adding `--reload` to the startup command enables automatic restarts during development (each restart discards in-memory sessions).

## External controller

Switch a game to **External**, then copy its game ID/API URL. Your harness reads the board and legal moves and posts actions with the observed revision. Open the copied share link to watch that exact game.

```sh
python3 examples/play_via_api.py --help
```

The example client can create a seeded external game or attach to an existing one and select random legal moves. It demonstrates the game interface without requiring a model. See [docs/api.md](docs/api.md) for endpoints and examples; interactive API documentation is at [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## Verify

```sh
uv run pytest
npm run build --prefix frontend
npm run lint --prefix frontend
npm run format:check --prefix frontend
```

Backend tests cover merge rules, reproducibility, controller ownership and stale moves, and the model HTTP contract using a mock server. Real model inference needs a configured endpoint. Fine-tuning and experiment orchestration are outside this app.

Frontend linting includes React Hooks rules for hook dependencies, rendering purity, and effect usage. `npm run format --prefix frontend` applies consistent source formatting.
