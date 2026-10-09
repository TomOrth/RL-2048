interface SessionDetailsProps {
  gameId: string | null;
  seed: number | null;
  moveCount: number | null;
  revision: number | null;
  onShare: (kind: "game-id" | "share-url" | "api-url") => void;
  onExport: () => void;
}

export function SessionDetails({
  gameId,
  seed,
  moveCount,
  revision,
  onShare,
  onExport,
}: SessionDetailsProps) {
  return (
    <section className="inspect-section session-section">
      <div className="section-title">
        <h2>Session</h2>
        <span className="revision">REV {revision ?? "—"}</span>
      </div>
      <div className="session-id">
        <span>GAME ID</span>
        <button onClick={() => onShare("game-id")} disabled={!gameId}>
          {gameId ? `${gameId.slice(0, 19)}…` : "Waiting for game"} <b>⧉</b>
        </button>
      </div>
      <div className="session-meta">
        <div>
          <span>SEED</span>
          <strong>{seed ?? "—"}</strong>
        </div>
        <div>
          <span>MOVES</span>
          <strong>{moveCount ?? "—"}</strong>
        </div>
      </div>
      <div className="session-actions">
        <button onClick={() => onShare("share-url")} disabled={!gameId}>
          Copy share link <span>↗</span>
        </button>
        <button onClick={() => onShare("api-url")} disabled={!gameId}>
          Copy API URL <span>↗</span>
        </button>
        <button onClick={onExport} disabled={!gameId}>
          Export JSON <span>↓</span>
        </button>
      </div>
    </section>
  );
}
