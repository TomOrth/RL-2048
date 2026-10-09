import { ControllerPanel } from "./components/ControllerPanel";
import { GamePanel } from "./components/GamePanel";
import { SessionFooter } from "./components/GameControls";
import { LegalMoves, RecentMoves } from "./components/MoveInspector";
import { ModelConnection } from "./components/ModelConnection";
import { SessionDetails } from "./components/SessionDetails";
import { useGameSession } from "./hooks/useGameSession";

export default function App() {
  const session = useGameSession();
  const onNewGame = (seed?: number) => void session.createGame(seed);
  const modelSession = {
    gameId: session.gameId,
    game: session.game,
    applyObservedState: session.applyObservedState,
    applyMoveResult: session.applyMoveResult,
    setControl: session.setControl,
  };

  return (
    <main className="shell">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="2048 home">
          <span className="mark">2⁴</span> / PLAY
        </a>
        <div className="top-note">
          <span className="live-dot" /> LOCAL SESSION{" "}
          <span className="top-sep">·</span> API READY
        </div>
      </header>
      <section className="workspace">
        <GamePanel
          gameId={session.gameId}
          game={session.game}
          lastMove={session.lastMove}
          message={session.message}
          isBusy={session.isBusy}
          onMove={(direction) => void session.move(direction)}
          onNewGame={onNewGame}
          onDismissMessage={session.dismissMessage}
        />
        <aside className="inspector">
          <SessionDetails
            gameId={session.gameId}
            seed={session.seed}
            moveCount={session.game?.move_count ?? null}
            revision={session.game?.revision ?? null}
            onShare={(kind) => void session.share(kind)}
            onExport={() => void session.exportHistory()}
          />
          <ControllerPanel
            game={session.game}
            onControl={(mode, paused) => void session.setControl(mode, paused)}
          />
          <ModelConnection
            key={session.gameId ?? "no-game"}
            session={modelSession}
          />
          <LegalMoves moves={session.game?.legal_moves ?? []} />
          <RecentMoves history={session.history} />
        </aside>
      </section>
      <SessionFooter
        seed={session.seed}
        isBusy={session.isBusy}
        onNewGame={onNewGame}
      />
    </main>
  );
}
