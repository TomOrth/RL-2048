import { useRef } from "react";
import type { CSSProperties } from "react";
import type { Direction, GameState, MoveResult } from "../api/types";

function offsetForCells(delta: number): string {
  if (delta === 0) return "0%";
  const gapTerms = Array.from({ length: Math.abs(delta) }, () =>
    delta < 0 ? "- var(--board-gap)" : "+ var(--board-gap)",
  ).join(" ");
  return `calc(${delta * 100}% ${gapTerms})`;
}

interface BoardProps {
  game: GameState | null;
  gameId: string | null;
  lastMove: MoveResult | null;
  onMove: (direction: Direction) => void;
  onNewGame: () => void;
}

export function Board({
  game,
  gameId,
  lastMove,
  onMove,
  onNewGame,
}: BoardProps) {
  const touchStart = useRef<{ x: number; y: number } | null>(null);

  const finishSwipe = (x: number, y: number) => {
    const start = touchStart.current;
    touchStart.current = null;
    if (!start) return;
    const dx = x - start.x;
    const dy = y - start.y;
    if (Math.max(Math.abs(dx), Math.abs(dy)) < 24) return;
    onMove(
      Math.abs(dx) > Math.abs(dy)
        ? dx > 0
          ? "right"
          : "left"
        : dy > 0
          ? "down"
          : "up",
    );
  };

  return (
    <div
      className="board-wrap"
      onTouchStart={(event) => {
        touchStart.current = {
          x: event.touches[0].clientX,
          y: event.touches[0].clientY,
        };
      }}
      onTouchEnd={(event) =>
        finishSwipe(
          event.changedTouches[0].clientX,
          event.changedTouches[0].clientY,
        )
      }
    >
      {game ? (
        <div className="board" role="grid" aria-label="2048 game board">
          {game.board.flatMap((row, rowIndex) =>
            row.map((value, columnIndex) => {
              const spawned =
                lastMove?.spawned_tile?.row === rowIndex &&
                lastMove.spawned_tile.column === columnIndex;
              const transitions =
                lastMove?.transitions.filter(
                  (transition) =>
                    transition.to_row === rowIndex &&
                    transition.to_column === columnIndex,
                ) ?? [];
              const merged = transitions.some(
                (transition) => transition.merged,
              );
              const slide = transitions[0];
              const slideStyle = slide
                ? ({
                    "--from-x": offsetForCells(slide.from_column - columnIndex),
                    "--from-y": offsetForCells(slide.from_row - rowIndex),
                  } as CSSProperties)
                : undefined;

              return (
                <div
                  key={`${rowIndex}-${columnIndex}`}
                  role="gridcell"
                  aria-label={value ? String(value) : "empty"}
                  className={`cell ${value ? `tile tile-${value}` : ""} ${slide ? "sliding" : ""} ${spawned ? "born" : ""} ${merged ? "merged" : ""}`}
                  style={slideStyle}
                  data-value={value || ""}
                >
                  {value || ""}
                </div>
              );
            }),
          )}
        </div>
      ) : (
        <>
          <div className="board board-loading">
            <span className="spinner" />
            {gameId ? "Opening game…" : "Start a new game to play"}
          </div>
          {!gameId && (
            <div className="empty-overlay">
              <button onClick={onNewGame}>
                Start a game <span>↗</span>
              </button>
            </div>
          )}
        </>
      )}
      {game?.status === "game_over" && (
        <div className="game-over">
          <strong>Game over</strong>
          <span>No legal moves remain.</span>
          <button onClick={onNewGame}>
            Start again <b>↗</b>
          </button>
        </div>
      )}
    </div>
  );
}
