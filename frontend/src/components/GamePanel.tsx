import type { Direction, GameState, MoveResult } from "../api/types";
import { Board } from "./Board";
import { GameControls } from "./GameControls";

interface GamePanelProps {
  gameId: string | null;
  game: GameState | null;
  lastMove: MoveResult | null;
  message: string;
  isBusy: boolean;
  onMove: (direction: Direction) => void;
  onNewGame: (seed?: number) => void;
  onDismissMessage: () => void;
}

export function GamePanel({
  gameId,
  game,
  lastMove,
  message,
  isBusy,
  onMove,
  onNewGame,
  onDismissMessage,
}: GamePanelProps) {
  const isHuman = game?.control.mode === "human";
  const status =
    game?.status === "game_over"
      ? "Finished"
      : game?.control.mode === "builtin"
        ? "Model"
        : game?.control.mode === "external"
          ? "External"
          : game
            ? "Your turn"
            : "Connecting";

  return (
    <div className="game-column">
      <div className="heading-row">
        <div>
          <p className="eyebrow">THE NUMBER GAME</p>
          <h1>
            2048<span>.</span>
          </h1>
        </div>
        <button
          className="new-button"
          onClick={() => onNewGame()}
          disabled={isBusy}
        >
          <span>＋</span> New game
        </button>
      </div>
      <div className="score-row">
        <div className="score">
          <span>SCORE</span>
          <strong>{game?.score ?? "—"}</strong>
        </div>
        <div className="score">
          <span>BEST TILE</span>
          <strong>{game?.max_tile ?? "—"}</strong>
        </div>
        <div className="score status-score">
          <span>SESSION</span>
          <strong>{status}</strong>
        </div>
      </div>
      <Board
        game={game}
        gameId={gameId}
        lastMove={lastMove}
        onMove={onMove}
        onNewGame={onNewGame}
      />
      <GameControls
        enabled={isHuman}
        legalMoves={game?.legal_moves ?? []}
        isBusy={isBusy}
        onMove={onMove}
      />
      {message && (
        <div className="notice" role="status">
          <span>{message}</span>
          {gameId && !game && (
            <button className="notice-new" onClick={() => onNewGame()}>
              New game
            </button>
          )}
          <button onClick={onDismissMessage} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
      {game?.reached_2048 && (
        <div className="milestone">
          2048 reached <span>Keep going — the session stays live.</span>
        </div>
      )}
    </div>
  );
}
