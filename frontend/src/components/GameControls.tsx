import { useState } from "react";
import type { Direction } from "../api/types";

const DIRECTIONS: Direction[] = ["up", "left", "down", "right"];
const ARROWS: Record<Direction, string> = {
  up: "↑",
  down: "↓",
  left: "←",
  right: "→",
};

interface GameControlsProps {
  enabled: boolean;
  legalMoves: Direction[];
  isBusy: boolean;
  onMove: (direction: Direction) => void;
}

export function GameControls({
  enabled,
  legalMoves,
  isBusy,
  onMove,
}: GameControlsProps) {
  return (
    <div className="play-tools">
      <div className="direction-pad" aria-label="Move direction">
        {DIRECTIONS.map((direction) => (
          <button
            key={direction}
            className={`dir dir-${direction}`}
            aria-label={`Move ${direction}`}
            disabled={!enabled || isBusy || !legalMoves.includes(direction)}
            onClick={() => onMove(direction)}
          >
            {ARROWS[direction]}
          </button>
        ))}
      </div>
      <p>
        Use <b>↑ ↓ ← →</b> or <b>W A S D</b> to move
        <span className="mobile-hint"> · swipe the board</span>
      </p>
    </div>
  );
}

interface SessionFooterProps {
  seed: number | null;
  isBusy: boolean;
  onNewGame: (seed?: number) => void;
}

export function SessionFooter({ seed, isBusy, onNewGame }: SessionFooterProps) {
  const [seedInput, setSeedInput] = useState("");
  const requestedSeed = Number(seedInput);
  const validSeed =
    seedInput.trim() !== "" && Number.isSafeInteger(requestedSeed);

  return (
    <footer>
      <span>2048 / LOCAL PLAY</span>
      <button onClick={() => onNewGame(seed ?? undefined)} disabled={isBusy}>
        Replay with seed {seed ?? "—"} <b>↻</b>
      </button>
      <button onClick={() => onNewGame()} disabled={isBusy}>
        New random seed <b>↗</b>
      </button>
      <label className="seed-control">
        START WITH SEED
        <input
          aria-label="Starting seed"
          type="number"
          step="1"
          value={seedInput}
          onChange={(event) => setSeedInput(event.target.value)}
          placeholder="integer"
        />
        <button
          onClick={() => onNewGame(requestedSeed)}
          disabled={isBusy || !validSeed}
        >
          Start ↗
        </button>
      </label>
    </footer>
  );
}
