import type { GameState } from "../api/types";

interface ControllerPanelProps {
  game: GameState | null;
  onControl: (mode: "human" | "external" | "builtin", paused?: boolean) => void;
}

export function ControllerPanel({ game, onControl }: ControllerPanelProps) {
  const mode = game?.control.mode;
  const isPaused = game?.control.paused ?? false;
  const note =
    mode === "human"
      ? "Your moves are sent directly to this session."
      : mode === "external"
        ? "An external client owns moves. Take over to play."
        : mode === "builtin"
          ? isPaused
            ? "The built-in model is paused."
            : "The built-in model owns moves while running."
          : "Choose who controls this session.";

  return (
    <section className="inspect-section control-section">
      <div className="section-title">
        <h2>Controller</h2>
        <span className={`mode-pill ${mode ?? ""}`}>{mode ?? "—"}</span>
      </div>
      <div className="segmented">
        <button
          className={mode === "human" ? "selected" : ""}
          onClick={() => onControl("human")}
          disabled={!game}
        >
          Human
        </button>
        <button
          className={mode === "external" ? "selected" : ""}
          onClick={() => onControl("external")}
          disabled={!game}
        >
          External
        </button>
        <button
          className={mode === "builtin" ? "selected" : ""}
          onClick={() => onControl("builtin")}
          disabled={!game}
        >
          Model
        </button>
      </div>
      <p className="control-note">{note}</p>
      {game && mode !== "human" && (
        <div className="controller-actions">
          <button
            className="takeover"
            onClick={() => onControl(game.control.mode, !isPaused)}
          >
            {isPaused ? "Resume automation" : "Pause automation"}{" "}
            <span>{isPaused ? "▶" : "Ⅱ"}</span>
          </button>
          <button className="takeover" onClick={() => onControl("human")}>
            Take over <span>↗</span>
          </button>
        </div>
      )}
    </section>
  );
}
