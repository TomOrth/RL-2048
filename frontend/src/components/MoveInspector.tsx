import type { Direction, GameHistory } from "../api/types";

const ARROWS: Record<Direction, string> = {
  up: "↑",
  down: "↓",
  left: "←",
  right: "→",
};

export function LegalMoves({ moves }: { moves: Direction[] }) {
  return (
    <section className="inspect-section legal-section">
      <div className="section-title">
        <h2>Legal moves</h2>
        <span>{moves.length} available</span>
      </div>
      <div className="legal-moves">
        {moves.length ? (
          moves.map((move) => (
            <span key={move}>
              {ARROWS[move]} {move}
            </span>
          ))
        ) : (
          <span className="muted">Waiting for a game</span>
        )}
      </div>
    </section>
  );
}

export function RecentMoves({ history }: { history: GameHistory | null }) {
  const moves = history?.moves ?? [];
  return (
    <section className="inspect-section history-section">
      <div className="section-title">
        <h2>Recent moves</h2>
        <span>{moves.length} total</span>
      </div>
      {moves.length ? (
        <ol>
          {moves
            .slice(-6)
            .reverse()
            .map((move, index) => (
              <li key={`${move.revision_after}-${index}`}>
                <span className="history-dir">{ARROWS[move.direction]}</span>
                <span>{move.direction}</span>
                <span className="history-source">{move.source}</span>
                <span className="history-score">
                  {move.score_delta ? `+${move.score_delta}` : "—"}
                </span>
              </li>
            ))}
        </ol>
      ) : (
        <p className="empty-history">
          Moves appear here as the game progresses.
        </p>
      )}
    </section>
  );
}
