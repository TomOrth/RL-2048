"""OpenAI-compatible Chat Completions controller and per-game job manager."""

from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, ValidationError

from ..contracts import (
    ControlRequest,
    Direction,
    LLMCheckResponse,
    LLMSettingsRequest,
    LLMSettingsResponse,
    LLMStatus,
    MoveRequest,
    MoveResult,
)
from ..engine import legal_moves
from ..sessions import GameError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You control a 4x4 game of 2048. Choose the next move to maximize the final score and build the largest tile possible. Continue playing after reaching 2048.

Rules:
- The board lists rows from top to bottom and columns from left to right. 0 is an empty cell.
- A move slides ALL tiles toward the named edge: up, down, left, or right.
- Adjacent equal tiles merge in that direction into one tile with twice the value. Each tile can merge only once per move; the merged value is added to the score.
- After a legal move, a new tile appears in a uniformly random empty cell: 2 with probability 90%, otherwise 4. Its position is unknown when you choose.
- Only the listed legal moves are allowed. The game ends when no legal move remains.

Decision guidance:
- Compare the boards produced by the legal moves, accounting for the unknown new tile.
- Preserve empty cells and future legal moves; avoid trapping tiles or filling the board.
- Favor useful merges and arrangements that let equal tiles meet on later moves, rather than immediate points alone.
- When practical, keep the largest tile in a corner and arrange other large tiles in decreasing order along its edge. Relax this preference when needed to stay alive or create space.
- Choose for the current board; do not follow a fixed direction cycle.

Return a JSON object with exactly one field, direction, whose value is one of the listed legal moves. Do not include explanation or markdown."""


class _MoveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    direction: Direction


def _response_format(legal: list[str]) -> dict[str, Any]:
    """Build an independent strict JSON Schema constrained to this board."""
    schema = _MoveResponse.model_json_schema()
    schema["properties"]["direction"]["enum"] = list(legal)
    return {
        "type": "json_schema",
        "json_schema": {"name": "2048_move", "strict": True, "schema": schema},
    }


class LLMFailure(Exception):
    """Safe, user-facing inference failure."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class LLMStaleResponse(Exception):
    """Inference completed after the state or controller it observed changed."""


@dataclass(frozen=True)
class _Settings:
    url: str
    resolved_url: str
    model: str
    api_key: str | None
    max_tokens: int
    token_limit_field: str
    timeout_seconds: float
    delay_seconds: float

    def public(self) -> LLMSettingsResponse:
        return LLMSettingsResponse(
            url=self.url,
            resolved_url=self.resolved_url,
            model=self.model,
            api_key_configured=bool(self.api_key),
            max_tokens=self.max_tokens,
            token_limit_field=self.token_limit_field,  # type: ignore[arg-type]
            timeout_seconds=self.timeout_seconds,
            delay_seconds=self.delay_seconds,
        )


class LLMManager:
    def __init__(self, store: Any, client_factory: Callable[..., Any] = httpx.AsyncClient):
        self.store = store
        self.client_factory = client_factory
        self.settings: dict[str, _Settings] = {}
        self.statuses: dict[str, LLMStatus] = {}
        self._generations: dict[str, int] = {}
        self._jobs: dict[str, asyncio.Task[Any]] = {}
        self._run_tasks: dict[str, asyncio.Task[Any]] = {}
        self._retired_tasks: set[asyncio.Task[Any]] = set()
        self._job_lock = asyncio.Lock()
        self._closing = False

    def status(self, game_id: str) -> LLMStatus:
        self.store.state(game_id)  # preserve the API's game-not-found behavior
        current = self.statuses.get(game_id, LLMStatus())
        return current.model_copy(update={
            "configured": game_id in self.settings,
            "running": bool((task := self._run_tasks.get(game_id)) and not task.done()),
            "busy": bool((task := self._jobs.get(game_id)) and not task.done()),
        })

    async def on_control_change(self, game_id: str) -> None:
        await self._invalidate(game_id)

    async def shutdown(self) -> None:
        self._closing = True
        tasks = list(set(self._jobs.values()) | self._retired_tasks)
        self._jobs.clear()
        self._run_tasks.clear()
        self._retired_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _invalidate(self, game_id: str) -> None:
        self._generations[game_id] = self._generations.get(game_id, 0) + 1
        task = self._jobs.pop(game_id, None)
        run_task = self._run_tasks.get(game_id)
        if run_task is task:
            self._run_tasks.pop(game_id, None)
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            self._retired_tasks.add(task)
            task.add_done_callback(self._retired_tasks.discard)

    def put_settings(self, game_id: str, request: LLMSettingsRequest) -> LLMSettingsResponse:
        self.store.state(game_id)
        url = request.url.strip()
        model = request.model.strip()
        if not model:
            raise GameError(422, "invalid_llm_settings", "Model name must not be empty")
        try:
            resolved = resolve_completion_url(url)
        except ValueError as exc:
            raise GameError(422, "invalid_llm_url", str(exc)) from exc
        previous = self.settings.get(game_id)
        api_key = request.api_key if request.api_key is not None else (previous.api_key if previous else None)
        settings = _Settings(
            url=url,
            resolved_url=resolved,
            model=model,
            api_key=api_key or None,
            max_tokens=request.max_tokens,
            token_limit_field=request.token_limit_field,
            timeout_seconds=request.timeout_seconds,
            delay_seconds=request.delay_seconds,
        )
        self.settings[game_id] = settings
        self.statuses[game_id] = self.statuses.get(game_id, LLMStatus()).model_copy(update={"error": None})
        return settings.public()

    def get_settings(self, game_id: str) -> LLMSettingsResponse:
        self.store.state(game_id)
        settings = self.settings.get(game_id)
        if not settings:
            raise GameError(404, "llm_not_configured", "No model is configured for this game")
        return settings.public()

    async def check(self, game_id: str) -> LLMCheckResponse:
        state = self.store.state(game_id)
        settings = self._require_settings(game_id)
        board = state.board
        legal = state.legal_moves
        if not legal:
            board = [[0] * 4 for _ in range(4)]
            board[1][1] = 2
            legal = legal_moves(board)
        await self._claim(game_id)
        started = time.perf_counter()
        logger.info("LLM check started game=%s", game_id)
        try:
            _, content = await self._complete(settings, board, legal)
            logger.info("LLM check succeeded game=%s latency_ms=%.0f", game_id, (time.perf_counter() - started) * 1000)
            return LLMCheckResponse(ok=True, content=content, latency_ms=(time.perf_counter() - started) * 1000)
        except asyncio.CancelledError as exc:
            if self._closing:
                raise
            raise _api_error("Model check was discarded because settings or control changed", 409, "llm_response_discarded") from exc
        except LLMFailure as exc:
            logger.warning("LLM check failed game=%s: %s", game_id, exc.message)
            self._set_error(game_id, exc.message)
            raise _api_error(exc.message, 502) from exc
        finally:
            await self._release(game_id)

    async def step(self, game_id: str) -> MoveResult:
        settings = self._require_settings(game_id)
        state = self.store.state(game_id)
        _require_builtin(state)
        await self._claim(game_id)
        was_paused = state.control.paused
        try:
            if was_paused:
                state = self.store.control(game_id, ControlRequest(
                    mode="builtin", paused=False, expected_revision=state.revision
                ))
            generation = self._generations.get(game_id, 0)
            started = time.perf_counter()
            action, content = await self._complete(settings, state.board, state.legal_moves)
            self._assert_current(game_id, generation, state.revision)
            result = self.store.move(game_id, MoveRequest(
                direction=action, expected_revision=state.revision, source="builtin"
            ))
            self._set_success(game_id, content, action, (time.perf_counter() - started) * 1000)
            if was_paused:
                result.state = self.store.control(game_id, ControlRequest(
                    mode="builtin", paused=True, expected_revision=result.state.revision
                ))
            return result
        except asyncio.CancelledError as exc:
            if self._closing:
                raise
            raise _api_error("Model response was discarded because settings or control changed", 409, "llm_response_discarded") from exc
        except LLMStaleResponse as exc:
            raise _api_error(str(exc), 409, "llm_response_discarded") from exc
        except GameError as exc:
            if exc.code in {"stale_revision", "wrong_controller", "paused", "game_over"}:
                raise _api_error("Model response was discarded because the game changed", 409, "llm_response_discarded") from exc
            self._set_error(game_id, "Model request failed")
            raise
        except Exception as exc:
            message = exc.message if isinstance(exc, LLMFailure) else _safe_game_error(exc)
            self._pause_after_failure(game_id, message)
            if isinstance(exc, (LLMFailure,)):
                raise _api_error(message, 502) from exc
            raise
        finally:
            await self._release(game_id)

    async def start_run(self, game_id: str) -> LLMStatus:
        settings = self._require_settings(game_id)
        state = self.store.state(game_id)
        _require_builtin(state)
        if state.status != "ongoing":
            return self.status(game_id)
        if state.control.paused:
            state = self.store.control(game_id, ControlRequest(
                mode="builtin", paused=False, expected_revision=state.revision
            ))
        await self._claim(game_id)
        self.statuses[game_id] = self.statuses.get(game_id, LLMStatus()).model_copy(update={"error": None})
        generation = self._generations.get(game_id, 0)
        task = asyncio.create_task(self._run_loop(game_id, settings, generation), name=f"llm-run-{game_id}")
        self._jobs[game_id] = task
        self._run_tasks[game_id] = task
        return self.status(game_id)

    async def pause(self, game_id: str) -> LLMStatus:
        state = self.store.state(game_id)
        if state.control.mode != "builtin":
            raise _api_error("Game is not controlled by the built-in model", 409, "wrong_control_source")
        await self._invalidate(game_id)
        state = self.store.state(game_id)
        if state.control.mode == "builtin" and not state.control.paused:
            self.store.control(game_id, ControlRequest(
                mode="builtin", paused=True, expected_revision=state.revision
            ))
        status = self.statuses.get(game_id, LLMStatus()).model_copy(update={"error": None})
        self.statuses[game_id] = status
        return self.status(game_id)

    async def _run_loop(self, game_id: str, settings: _Settings, generation: int) -> None:
        try:
            while not self._closing:
                state = self.store.state(game_id)
                if state.control.mode != "builtin" or state.control.paused or state.status != "ongoing":
                    return
                started = time.perf_counter()
                try:
                    action, content = await self._complete(settings, state.board, state.legal_moves)
                    self._assert_current(game_id, generation, state.revision)
                    self.store.move(game_id, MoveRequest(
                        direction=action, expected_revision=state.revision, source="builtin"
                    ))
                    self._set_success(game_id, content, action, (time.perf_counter() - started) * 1000)
                except asyncio.CancelledError:
                    raise
                except LLMStaleResponse:
                    return
                except GameError as exc:
                    if exc.code in {"stale_revision", "wrong_controller", "paused", "game_over"}:
                        return
                    message = _safe_game_error(exc)
                    self._pause_after_failure(game_id, message)
                    return
                except Exception as exc:
                    message = exc.message if isinstance(exc, LLMFailure) else _safe_game_error(exc)
                    self._pause_after_failure(game_id, message)
                    return
                if settings.delay_seconds:
                    await asyncio.sleep(settings.delay_seconds)
        finally:
            if self._jobs.get(game_id) is asyncio.current_task():
                self._jobs.pop(game_id, None)
            if self._run_tasks.get(game_id) is asyncio.current_task():
                self._run_tasks.pop(game_id, None)

    async def _complete(self, settings: _Settings, board: list[list[int]], legal: list[str]) -> tuple[Direction, str]:
        if not legal:
            raise LLMFailure("The game has no legal moves")
        headers = {"Content-Type": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _board_prompt(board, legal)},
            ],
            "stream": False,
            settings.token_limit_field: settings.max_tokens,
            "response_format": _response_format(legal),
        }
        logger.info(
            "LLM request endpoint=%s model=%s %s=%s timeout_seconds=%s",
            settings.resolved_url, settings.model, settings.token_limit_field,
            settings.max_tokens, settings.timeout_seconds,
        )
        try:
            async with self.client_factory(timeout=settings.timeout_seconds) as client:
                response = await client.post(settings.resolved_url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            logger.warning("LLM transport timed out type=%s", type(exc).__name__)
            raise LLMFailure("Model request timed out") from exc
        except httpx.HTTPError as exc:
            # Do not surface exception strings, which may include request headers or credentials.
            logger.warning("LLM transport failed type=%s", type(exc).__name__)
            raise LLMFailure("Could not connect to the model server") from exc
        logger.info("LLM HTTP response status=%s content_type=%s", response.status_code, response.headers.get("content-type", "unknown"))
        if response.status_code >= 400:
            raise LLMFailure(_http_failure(response.status_code))
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise LLMFailure("Model server returned malformed JSON") from exc
        if not isinstance(body, dict) or not isinstance(body.get("choices"), list) or not body["choices"]:
            raise LLMFailure("Model server returned no completion choice")
        usage = body.get("usage")
        if isinstance(usage, dict):
            details = usage.get("completion_tokens_details")
            reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else None
            completion_tokens = usage.get("completion_tokens")
            logger.info(
                "LLM token usage completion_tokens=%s reasoning_tokens=%s",
                completion_tokens if type(completion_tokens) is int else "unknown",
                reasoning_tokens if type(reasoning_tokens) is int else "unknown",
            )
        choice = body["choices"][0]
        if not isinstance(choice, dict):
            raise LLMFailure("Model server returned an unexpected completion shape")
        reason = choice.get("finish_reason")
        logger.info("LLM completion finish_reason=%s", reason)
        if reason == "length":
            raise LLMFailure(
                f"Model response was truncated by the token limit ({settings.max_tokens}). "
                "Increase Token limit, save settings, and try again."
            )
        if reason == "content_filter":
            raise LLMFailure("The model response was blocked by a content filter")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise LLMFailure("Model server returned an unexpected completion shape")
        if message.get("refusal"):
            raise LLMFailure("The model refused to choose a move")
        if message.get("tool_calls") or reason == "tool_calls":
            raise LLMFailure("The model returned a tool call instead of a move")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMFailure("Model returned an empty or non-text response")
        try:
            move = _MoveResponse.model_validate_json(content, strict=True)
        except ValidationError as exc:
            logger.info("LLM response validation failed type=%s", type(exc).__name__)
            raise LLMFailure("Model response must be a JSON object with one legal direction field") from exc
        action_text = move.direction
        if action_text not in legal:
            raise LLMFailure(f"Model chose illegal move: {action_text}")
        logger.info("LLM selected action=%s", action_text)
        return action_text, move.model_dump_json()

    async def _claim(self, game_id: str) -> None:
        async with self._job_lock:
            task = self._jobs.get(game_id)
            if task is not None and not task.done():
                raise _api_error("A model request is already active for this game", 409, "llm_busy")
            self._jobs[game_id] = asyncio.current_task()  # type: ignore[assignment]

    async def _release(self, game_id: str) -> None:
        async with self._job_lock:
            if self._jobs.get(game_id) is asyncio.current_task():
                self._jobs.pop(game_id, None)

    def _assert_current(self, game_id: str, generation: int, revision: int) -> None:
        if self._generations.get(game_id, 0) != generation:
            raise LLMStaleResponse("Model response was discarded because settings or control changed")
        state = self.store.state(game_id)
        if (state.revision != revision or state.control.mode != "builtin" or state.control.paused
                or state.status != "ongoing"):
            raise LLMStaleResponse("Model response was discarded because the game changed")

    def _require_settings(self, game_id: str) -> _Settings:
        self.store.state(game_id)
        settings = self.settings.get(game_id)
        if not settings:
            raise _api_error("No model is configured for this game", 404, "llm_not_configured")
        return settings

    def _set_error(self, game_id: str, message: str) -> None:
        self.statuses[game_id] = self.statuses.get(game_id, LLMStatus()).model_copy(update={"error": message})

    def _set_success(self, game_id: str, content: str, action: Direction, latency: float) -> None:
        self.statuses[game_id] = self.statuses.get(game_id, LLMStatus()).model_copy(update={
            "error": None, "last_response": content, "last_action": action, "last_latency_ms": latency,
        })

    def _pause_after_failure(self, game_id: str, message: str) -> None:
        self._set_error(game_id, message)
        try:
            state = self.store.state(game_id)
            if state.control.mode == "builtin" and not state.control.paused:
                self.store.control(game_id, ControlRequest(
                    mode="builtin", paused=True, expected_revision=state.revision
                ))
        except Exception:
            pass


def create_llm_router(store: Any, client_factory: Callable[..., Any] = httpx.AsyncClient) -> tuple[APIRouter, LLMManager]:
    router = APIRouter()
    manager = LLMManager(store, client_factory)

    @router.get("/api/games/{game_id}/llm/settings", response_model=LLMSettingsResponse)
    async def get_settings(game_id: str) -> LLMSettingsResponse:
        return manager.get_settings(game_id)

    @router.put("/api/games/{game_id}/llm/settings", response_model=LLMSettingsResponse)
    async def put_settings(game_id: str, request: LLMSettingsRequest) -> LLMSettingsResponse:
        await manager._invalidate(game_id)
        return manager.put_settings(game_id, request)

    @router.get("/api/games/{game_id}/llm/status", response_model=LLMStatus)
    async def get_status(game_id: str) -> LLMStatus:
        return manager.status(game_id)

    @router.post("/api/games/{game_id}/llm/check", response_model=LLMCheckResponse)
    async def check(game_id: str) -> LLMCheckResponse:
        return await manager.check(game_id)

    @router.post("/api/games/{game_id}/llm/step", response_model=MoveResult)
    async def step(game_id: str) -> MoveResult:
        return await manager.step(game_id)

    @router.post("/api/games/{game_id}/llm/run", response_model=LLMStatus)
    async def run(game_id: str) -> LLMStatus:
        return await manager.start_run(game_id)

    @router.post("/api/games/{game_id}/llm/pause", response_model=LLMStatus)
    async def pause(game_id: str) -> LLMStatus:
        return await manager.pause(game_id)

    return router, manager


def resolve_completion_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        _ = parts.port  # Force validation of malformed ports before making a request.
    except ValueError as exc:
        raise ValueError("Model URL is invalid") from exc
    if parts.scheme not in ("http", "https") or not parts.netloc or not parts.hostname:
        raise ValueError("Model URL must be an absolute HTTP or HTTPS URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Model URL must not contain credentials")
    if parts.query or parts.fragment:
        raise ValueError("Model URL must not contain a query string or fragment")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        resolved_path = path
    else:
        resolved_path = f"{path}/chat/completions" if path else "/v1/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, resolved_path, "", ""))


def _board_prompt(board: list[list[int]], legal: list[str]) -> str:
    rows = "\n".join(" ".join(str(value) for value in row) for row in board)
    return f"Board (rows top to bottom; columns left to right; 0 means empty):\n{rows}\nLegal moves: {', '.join(legal)}"


def _http_failure(status: int) -> str:
    if status in (401, 403):
        return f"Model server rejected authentication (HTTP {status})"
    if status == 404:
        return "Model endpoint or configured model was not found (HTTP 404)"
    if status == 429:
        return "Model server rate limit reached (HTTP 429)"
    if status in (400, 422):
        return (
            f"Model server rejected the request (HTTP {status}); it may not support the requested JSON Schema "
            "or another request parameter"
        )
    if status >= 500:
        return f"Model server failed (HTTP {status})"
    return f"Model server rejected the request (HTTP {status})"


def _api_error(message: str, status_code: int, code: str = "llm_error") -> GameError:
    return GameError(status_code, code, message)


def _require_builtin(state: Any) -> None:
    if state.control.mode != "builtin":
        raise _api_error("Game is not controlled by the built-in model", 409, "wrong_control_source")
    if state.status != "ongoing":
        raise _api_error("Game is over", 409, "game_over")


def _safe_game_error(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code == "stale_revision":
        return "Model response was discarded because the game changed"
    if code in ("wrong_control_source", "paused", "game_over"):
        return "Model response was discarded because model control is no longer active"
    return "Model request failed"
