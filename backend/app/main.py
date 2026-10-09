"""FastAPI application for local 2048 games."""

from __future__ import annotations

import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .contracts import ControlRequest, CreateGameRequest, MoveRequest
from .sessions import GameError, SessionStore
from .llm.router import create_llm_router


def create_app(store: SessionStore | None = None) -> FastAPI:
    # Uvicorn configures its own loggers, not the application's root logger.
    # Leave an explicitly configured logging setup intact when embedded.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    game_store = store or SessionStore()
    llm_router, manager = create_llm_router(game_store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await manager.shutdown()

    app = FastAPI(title="2048 Game API", lifespan=lifespan)
    app.state.store = game_store
    app.state.llm_manager = manager
    app.include_router(llm_router)

    @app.exception_handler(GameError)
    async def game_error_handler(_request: Request, exc: GameError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's default error body can echo submitted settings, including keys.
        messages = [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "; ".join(messages)}})

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/games")
    async def create_game(request: CreateGameRequest | None = None):
        request = request or CreateGameRequest()
        return app.state.store.create(seed=request.seed, mode=request.mode)

    @app.get("/api/games/{game_id}")
    async def get_game(game_id: str):
        return app.state.store.state(game_id)

    @app.post("/api/games/{game_id}/moves")
    async def move(game_id: str, request: MoveRequest):
        return app.state.store.move(game_id, request)

    @app.put("/api/games/{game_id}/control")
    async def update_control(game_id: str, request: ControlRequest):
        before = app.state.store.state(game_id)
        state = app.state.store.control(game_id, request)
        if state.revision != before.revision:
            await manager.on_control_change(game_id)
        return state

    @app.get("/api/games/{game_id}/history")
    async def get_history(game_id: str):
        return app.state.store.history(game_id)

    # Serve built frontend files when available. This fallback is deliberately
    # registered after API routes and keeps unknown /api paths as JSON 404s.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        resolved_dist = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def frontend(path: str):
            if path == "api" or path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            candidate = (resolved_dist / path).resolve()
            if candidate != resolved_dist and resolved_dist not in candidate.parents:
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            if candidate.is_file():
                return FileResponse(candidate)
            index = resolved_dist / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

    return app


app = create_app()
