from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["up", "down", "left", "right"]
ControlMode = Literal["human", "external", "builtin"]


class Control(BaseModel):
    mode: ControlMode = "human"
    paused: bool = False


class GameState(BaseModel):
    id: str
    revision: int
    board: list[list[int]]
    score: int
    max_tile: int
    legal_moves: list[Direction]
    status: Literal["ongoing", "game_over"]
    reached_2048: bool
    move_count: int
    control: Control


class CreateGameRequest(BaseModel):
    seed: int | None = Field(default=None, ge=-(2**53 - 1), le=2**53 - 1)
    mode: ControlMode = "human"


class CreateGameResponse(BaseModel):
    state: GameState
    seed: int


class MoveRequest(BaseModel):
    direction: Direction
    expected_revision: int = Field(ge=0)
    source: ControlMode = "human"


class ControlRequest(BaseModel):
    mode: ControlMode
    paused: bool = False
    expected_revision: int = Field(ge=0)


class SpawnedTile(BaseModel):
    row: int
    column: int
    value: int


class TileTransition(BaseModel):
    from_row: int
    from_column: int
    to_row: int
    to_column: int
    value: int
    merged: bool = False


class MoveResult(BaseModel):
    state: GameState
    moved: bool
    score_delta: int
    spawned_tile: SpawnedTile | None = None
    transitions: list[TileTransition] = Field(default_factory=list)


class LLMSettingsRequest(BaseModel):
    url: str
    model: str
    api_key: str | None = None  # None preserves existing key; empty string clears it.
    max_tokens: int = Field(default=64, ge=1, le=32768)
    token_limit_field: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    timeout_seconds: float = Field(default=30, ge=1, le=300)
    delay_seconds: float = Field(default=0.4, ge=0, le=60)


class LLMSettingsResponse(BaseModel):
    url: str
    resolved_url: str
    model: str
    api_key_configured: bool
    max_tokens: int
    token_limit_field: Literal["max_completion_tokens", "max_tokens"]
    timeout_seconds: float
    delay_seconds: float


class LLMStatus(BaseModel):
    configured: bool = False
    running: bool = False
    busy: bool = False
    error: str | None = None
    last_response: str | None = None
    last_action: Direction | None = None
    last_latency_ms: float | None = None


class LLMCheckResponse(BaseModel):
    ok: bool
    content: str
    latency_ms: float
