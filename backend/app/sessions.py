"""Thread-safe in-memory game sessions and history export."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from random import Random, SystemRandom
from threading import RLock
from uuid import uuid4

from .contracts import (
    Control, ControlMode, ControlRequest, CreateGameResponse, GameState,
    MoveRequest, MoveResult,
)
from .engine import Board, legal_moves, max_tile, new_board, play

MAX_SAFE_SEED = (1 << 53) - 1


class GameError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class _Session:
    game_id: str
    seed: int
    rng: Random
    board: Board
    initial_board: Board
    score: int = 0
    revision: int = 0
    move_count: int = 0
    reached_2048: bool = False
    control: Control = field(default_factory=Control)
    moves: list[dict] = field(default_factory=list)
    lock: RLock = field(default_factory=RLock)


class SessionStore:
    """An in-memory store whose snapshots and mutations are isolated per game."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._sessions_lock = RLock()

    def create(self, seed: int | None = None, mode: ControlMode = "human") -> CreateGameResponse:
        if seed is not None and (
            not isinstance(seed, int) or isinstance(seed, bool)
            or seed < -MAX_SAFE_SEED or seed > MAX_SAFE_SEED
        ):
            raise GameError(422, "invalid_seed", f"Seed must be an integer between {-MAX_SAFE_SEED} and {MAX_SAFE_SEED}.")
        chosen_seed = seed if seed is not None else SystemRandom().randrange(0, 1 << 53)
        rng = Random(chosen_seed)
        board = new_board(rng)
        session = _Session(
            game_id=str(uuid4()), seed=chosen_seed, rng=rng, board=board,
            initial_board=[row[:] for row in board], reached_2048=max_tile(board) >= 2048,
            control=Control(mode=mode, paused=False),
        )
        with self._sessions_lock:
            self._sessions[session.game_id] = session
        with session.lock:
            return CreateGameResponse(state=self._state(session), seed=chosen_seed)

    def state(self, game_id: str) -> GameState:
        session = self._get(game_id)
        with session.lock:
            return self._state(session)

    def move(self, game_id: str, request: MoveRequest) -> MoveResult:
        session = self._get(game_id)
        with session.lock:
            self._check_revision(session, request.expected_revision)
            if session.control.mode != request.source:
                raise GameError(409, "wrong_controller", "The game is controlled by a different source.")
            if request.source != "human" and session.control.paused:
                raise GameError(409, "paused", "Automated control is paused.")
            if self._status(session) == "game_over":
                raise GameError(409, "game_over", "The game is over; start a new game to continue.")

            before = [row[:] for row in session.board]
            revision_before = session.revision
            outcome = play(session.board, request.direction, session.rng)
            if outcome.moved:
                session.board = outcome.board
                session.score += outcome.score_delta
                session.move_count += 1
                session.revision += 1
                session.reached_2048 = session.reached_2048 or max_tile(session.board) >= 2048
            state = self._state(session)
            session.moves.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": request.source,
                "direction": request.direction,
                "moved": outcome.moved,
                "board_before": before,
                "board_after": [row[:] for row in session.board],
                "score_delta": outcome.score_delta,
                "spawned_tile": outcome.spawned_tile.model_dump() if outcome.spawned_tile else None,
                "revision_before": revision_before,
                "revision_after": session.revision,
            })
            return MoveResult(
                state=state, moved=outcome.moved, score_delta=outcome.score_delta,
                spawned_tile=outcome.spawned_tile, transitions=outcome.transitions,
            )

    def control(self, game_id: str, request: ControlRequest) -> GameState:
        session = self._get(game_id)
        with session.lock:
            self._check_revision(session, request.expected_revision)
            if session.control.mode != request.mode or session.control.paused != request.paused:
                session.control = Control(mode=request.mode, paused=request.paused)
                session.revision += 1
            return self._state(session)

    def history(self, game_id: str) -> dict:
        session = self._get(game_id)
        with session.lock:
            return {
                "schema_version": 1,
                "game_id": session.game_id,
                "seed": session.seed,
                "initial_board": [row[:] for row in session.initial_board],
                "moves": deepcopy(session.moves),
                "final_state": self._state(session).model_dump(mode="json"),
            }

    def _get(self, game_id: str) -> _Session:
        with self._sessions_lock:
            session = self._sessions.get(game_id)
        if session is None:
            raise GameError(404, "game_not_found", "Game not found.")
        return session

    @staticmethod
    def _check_revision(session: _Session, expected_revision: int) -> None:
        if expected_revision != session.revision:
            raise GameError(409, "stale_revision", "The game changed since this request was prepared.")

    @staticmethod
    def _status(session: _Session) -> str:
        return "ongoing" if legal_moves(session.board) else "game_over"

    @classmethod
    def _state(cls, session: _Session) -> GameState:
        return GameState(
            id=session.game_id,
            revision=session.revision,
            board=[row[:] for row in session.board],
            score=session.score,
            max_tile=max_tile(session.board),
            legal_moves=legal_moves(session.board),
            status=cls._status(session),
            reached_2048=session.reached_2048,
            move_count=session.move_count,
            control=session.control.model_copy(deep=True),
        )
