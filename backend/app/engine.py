"""Pure 2048 rules and deterministic random tile spawning."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from .contracts import Direction, SpawnedTile, TileTransition

Board = list[list[int]]
SIZE = 4
DIRECTIONS: tuple[Direction, ...] = ("up", "down", "left", "right")


@dataclass(frozen=True)
class MoveOutcome:
    board: Board
    score_delta: int
    spawned_tile: SpawnedTile | None
    transitions: list[TileTransition]
    moved: bool


def new_board(rng: Random) -> Board:
    board = [[0 for _ in range(SIZE)] for _ in range(SIZE)]
    spawn_tile(board, rng)
    spawn_tile(board, rng)
    return board


def slide(board: Board, direction: Direction) -> tuple[Board, int, list[TileTransition]]:
    """Slide tiles without spawning; a source tile can merge at most once."""
    result = [[0 for _ in range(SIZE)] for _ in range(SIZE)]
    score_delta = 0
    transitions: list[TileTransition] = []

    # Every line is represented from the edge toward which tiles move.
    for line_index in range(SIZE):
        coords = _line_coords(direction, line_index)
        occupied = [(coord, board[coord[0]][coord[1]]) for coord in coords if board[coord[0]][coord[1]]]
        out_index = 0
        i = 0
        while i < len(occupied):
            (from_a, value_a) = occupied[i]
            target = coords[out_index]
            if i + 1 < len(occupied) and occupied[i + 1][1] == value_a:
                from_b, _ = occupied[i + 1]
                merged_value = value_a * 2
                result[target[0]][target[1]] = merged_value
                score_delta += merged_value
                transitions.append(TileTransition(
                    from_row=from_a[0], from_column=from_a[1], to_row=target[0], to_column=target[1], value=value_a, merged=True
                ))
                transitions.append(TileTransition(
                    from_row=from_b[0], from_column=from_b[1], to_row=target[0], to_column=target[1], value=value_a, merged=True
                ))
                i += 2
            else:
                result[target[0]][target[1]] = value_a
                transitions.append(TileTransition(
                    from_row=from_a[0], from_column=from_a[1], to_row=target[0], to_column=target[1], value=value_a, merged=False
                ))
                i += 1
            out_index += 1
    return result, score_delta, transitions


def play(board: Board, direction: Direction, rng: Random) -> MoveOutcome:
    """Apply a move and spawn iff the board changed. No-op leaves RNG untouched."""
    changed, score_delta, transitions = slide(board, direction)
    if changed == board:
        return MoveOutcome(_copy_board(board), 0, None, [], False)
    spawned = spawn_tile(changed, rng)
    return MoveOutcome(changed, score_delta, spawned, transitions, True)


def legal_moves(board: Board) -> list[Direction]:
    return [direction for direction in DIRECTIONS if slide(board, direction)[0] != board]


def max_tile(board: Board) -> int:
    return max((value for row in board for value in row), default=0)


def spawn_tile(board: Board, rng: Random) -> SpawnedTile | None:
    empty = [(r, c) for r in range(SIZE) for c in range(SIZE) if board[r][c] == 0]
    if not empty:
        return None
    row, column = rng.choice(empty)
    value = 4 if rng.random() >= 0.9 else 2
    board[row][column] = value
    return SpawnedTile(row=row, column=column, value=value)


def _line_coords(direction: Direction, line: int) -> list[tuple[int, int]]:
    if direction == "left":
        return [(line, c) for c in range(SIZE)]
    if direction == "right":
        return [(line, c) for c in reversed(range(SIZE))]
    if direction == "up":
        return [(r, line) for r in range(SIZE)]
    return [(r, line) for r in reversed(range(SIZE))]


def _copy_board(board: Board) -> Board:
    return [row[:] for row in board]
