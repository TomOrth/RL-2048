import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  ControlMode,
  Direction,
  GameHistory,
  GameState,
  MoveResult,
} from "../api/types";

const KEY_DIRECTIONS: Record<string, Direction> = {
  arrowup: "up",
  w: "up",
  arrowdown: "down",
  s: "down",
  arrowleft: "left",
  a: "left",
  arrowright: "right",
  d: "right",
};

export interface GameSession {
  gameId: string | null;
  game: GameState | null;
  seed: number | null;
  history: GameHistory | null;
  message: string;
  isBusy: boolean;
  lastMove: MoveResult | null;
  applyState: (next: GameState) => void;
  applyObservedState: (next: GameState) => void;
  applyMoveResult: (result: MoveResult) => void;
  move: (direction: Direction) => Promise<void>;
  createGame: (seed?: number) => Promise<void>;
  setControl: (
    mode: ControlMode,
    paused?: boolean,
    signal?: AbortSignal,
  ) => Promise<GameState | null>;
  share: (kind: "game-id" | "share-url" | "api-url") => Promise<void>;
  exportHistory: () => Promise<void>;
  dismissMessage: () => void;
}

function readInitialGameId(): string | null {
  const queryId = new URLSearchParams(window.location.search).get("game");
  return queryId || window.localStorage.getItem("2048-game-id");
}

export function useGameSession(): GameSession {
  const [gameId, setGameId] = useState(readInitialGameId);
  const [game, setGame] = useState<GameState | null>(null);
  const [seed, setSeed] = useState<number | null>(null);
  const [history, setHistory] = useState<GameHistory | null>(null);
  const [message, setMessage] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [lastMove, setLastMove] = useState<MoveResult | null>(null);
  const gameSnapshot = useRef<GameState | null>(null);
  const activeGameId = useRef(gameId);
  const revision = useRef(-1);
  const moveInFlight = useRef(false);
  const creationSequence = useRef(0);
  const activeRequests = useRef(new Set<AbortController>());

  const createController = useCallback(() => {
    const controller = new AbortController();
    activeRequests.current.add(controller);
    return controller;
  }, []);

  const releaseController = useCallback((controller: AbortController) => {
    activeRequests.current.delete(controller);
  }, []);

  useEffect(
    () => () => {
      activeRequests.current.forEach((controller) => controller.abort());
      activeRequests.current.clear();
    },
    [],
  );

  const applyState = useCallback((next: GameState) => {
    if (activeGameId.current !== next.id || next.revision < revision.current)
      return;
    revision.current = next.revision;
    gameSnapshot.current = next;
    setGame(next);
  }, []);

  const applyMoveResult = useCallback(
    (result: MoveResult) => {
      if (
        activeGameId.current !== result.state.id ||
        result.state.revision < revision.current
      )
        return;
      setLastMove(result);
      applyState(result.state);
    },
    [applyState],
  );

  const applyObservedState = useCallback(
    (next: GameState) => {
      if (activeGameId.current !== next.id || next.revision < revision.current)
        return;
      if (next.revision > revision.current) setLastMove(null);
      applyState(next);
    },
    [applyState],
  );

  const refreshState = useCallback(
    async (id: string, signal?: AbortSignal) => {
      const next = await api.state(id, signal);
      if (activeGameId.current !== id) return;
      applyState(next);
    },
    [applyState],
  );

  const selectGame = useCallback((id: string, initialState?: GameState) => {
    activeGameId.current = id;
    revision.current = initialState?.revision ?? -1;
    gameSnapshot.current = initialState ?? null;
    setGameId(id);
    setGame(initialState ?? null);
    setSeed(null);
    setHistory(null);
    setLastMove(null);
    setMessage("");
  }, []);

  useEffect(() => {
    if (!gameId) {
      activeGameId.current = null;
      gameSnapshot.current = null;
      window.localStorage.removeItem("2048-game-id");
      const url = new URL(window.location.href);
      url.searchParams.delete("game");
      window.history.replaceState(null, "", url);
      return;
    }

    activeGameId.current = gameId;
    window.localStorage.setItem("2048-game-id", gameId);
    const url = new URL(window.location.href);
    url.searchParams.set("game", gameId);
    window.history.replaceState(null, "", url);

    const controller = new AbortController();
    void (async () => {
      try {
        const [current, log] = await Promise.all([
          api.state(gameId, controller.signal),
          api.history(gameId, controller.signal),
        ]);
        if (controller.signal.aborted || activeGameId.current !== gameId)
          return;
        applyState(current);
        setHistory(log);
        setSeed(log.seed);
      } catch (error) {
        if (!controller.signal.aborted && activeGameId.current === gameId) {
          setMessage(
            error instanceof Error
              ? error.message
              : "Could not open this game.",
          );
        }
      }
    })();

    return () => controller.abort();
  }, [gameId, applyState]);

  useEffect(() => {
    if (!gameId) return;
    let stopped = false;
    let inFlight = false;
    let pollCount = 0;
    let timer = 0;
    let controller: AbortController | null = null;

    const poll = async () => {
      if (stopped || inFlight || document.hidden) return;
      inFlight = true;
      controller = new AbortController();
      try {
        pollCount += 1;
        const [current, log] = await Promise.all([
          api.state(gameId, controller.signal),
          pollCount % 6 === 0
            ? api.history(gameId, controller.signal).catch(() => null)
            : Promise.resolve(null),
        ]);
        if (!stopped && activeGameId.current === gameId) {
          applyObservedState(current);
          if (log) {
            setHistory(log);
            setSeed(log.seed);
          }
        }
      } catch (error) {
        if (
          !stopped &&
          !controller.signal.aborted &&
          activeGameId.current === gameId
        ) {
          setMessage(
            error instanceof Error ? error.message : "Connection interrupted.",
          );
        }
      } finally {
        inFlight = false;
        controller = null;
        if (!stopped && !document.hidden) timer = window.setTimeout(poll, 350);
      }
    };

    const onVisibilityChange = () => {
      window.clearTimeout(timer);
      if (document.hidden) controller?.abort();
      else if (!inFlight && !stopped) timer = window.setTimeout(poll, 0);
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    if (!document.hidden) timer = window.setTimeout(poll, 350);

    return () => {
      stopped = true;
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [gameId, applyObservedState]);

  const move = useCallback(
    async (direction: Direction) => {
      const currentGame = gameSnapshot.current;
      if (
        !currentGame ||
        currentGame.control.mode !== "human" ||
        currentGame.status !== "ongoing" ||
        moveInFlight.current
      )
        return;
      const id = currentGame.id;
      const controller = createController();
      moveInFlight.current = true;
      setIsBusy(true);
      setMessage("");
      try {
        const result = await api.move(
          id,
          direction,
          currentGame.revision,
          controller.signal,
        );
        if (activeGameId.current !== id) return;
        if (result.state.revision >= revision.current) setLastMove(result);
        applyMoveResult(result);
        const historyController = createController();
        void api
          .history(id, historyController.signal)
          .then((log) => {
            if (
              !historyController.signal.aborted &&
              activeGameId.current === id
            )
              setHistory(log);
          })
          .catch(() => undefined)
          .finally(() => releaseController(historyController));
      } catch (error) {
        if (!controller.signal.aborted && activeGameId.current === id) {
          const message =
            error instanceof Error ? error.message : "Move failed.";
          try {
            await refreshState(id, controller.signal);
          } catch {
            // Keep the original move error visible if refreshing also fails.
          }
          if (activeGameId.current === id) setMessage(message);
        }
      } finally {
        releaseController(controller);
        moveInFlight.current = false;
        if (!controller.signal.aborted && activeGameId.current === id)
          setIsBusy(false);
      }
    },
    [applyMoveResult, refreshState, createController, releaseController],
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target?.isContentEditable ||
        /INPUT|TEXTAREA|SELECT/.test(target?.tagName ?? "")
      )
        return;
      const key = event.key.toLowerCase();
      const direction: Direction | null = KEY_DIRECTIONS[key] ?? null;
      if (direction) {
        event.preventDefault();
        void move(direction);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [move]);

  const createGame = useCallback(
    async (requestedSeed?: number) => {
      const request = ++creationSequence.current;
      const controller = createController();
      setIsBusy(true);
      setMessage("");
      try {
        const created = await api.create(requestedSeed, controller.signal);
        if (controller.signal.aborted || request !== creationSequence.current)
          return;
        selectGame(created.state.id, created.state);
        setSeed(created.seed);
      } catch (error) {
        if (
          !controller.signal.aborted &&
          request === creationSequence.current
        ) {
          setMessage(
            error instanceof Error ? error.message : "Could not start a game.",
          );
        }
      } finally {
        releaseController(controller);
        if (!controller.signal.aborted && request === creationSequence.current)
          setIsBusy(false);
      }
    },
    [selectGame, createController, releaseController],
  );

  const setControl = useCallback(
    async (mode: ControlMode, paused = false, signal?: AbortSignal) => {
      const currentGame = gameSnapshot.current;
      if (!currentGame) return null;
      const id = currentGame.id;
      const controller = createController();
      try {
        const updated = await api.control(
          id,
          mode,
          paused,
          currentGame.revision,
          signal ?? controller.signal,
        );
        if (
          signal?.aborted ||
          controller.signal.aborted ||
          activeGameId.current !== id
        )
          return null;
        applyObservedState(updated);
        setMessage("");
        return updated;
      } catch (error) {
        if (
          !signal?.aborted &&
          !controller.signal.aborted &&
          activeGameId.current === id
        ) {
          setMessage(
            error instanceof Error ? error.message : "Control change failed.",
          );
        }
        return null;
      } finally {
        releaseController(controller);
      }
    },
    [applyObservedState, createController, releaseController],
  );

  const share = useCallback(
    async (kind: "game-id" | "share-url" | "api-url") => {
      if (!gameId) return;
      const value =
        kind === "game-id"
          ? gameId
          : kind === "share-url"
            ? `${window.location.origin}/?game=${gameId}`
            : `${window.location.origin}/api/games/${gameId}`;
      try {
        await navigator.clipboard.writeText(value);
        if (activeGameId.current === gameId) setMessage("Copied to clipboard.");
      } catch {
        if (activeGameId.current === gameId)
          setMessage("Clipboard access is unavailable.");
      }
    },
    [gameId],
  );

  const exportHistory = useCallback(async () => {
    if (!gameId) return;
    const id = gameId;
    const controller = createController();
    try {
      const log = await api.history(id, controller.signal);
      if (controller.signal.aborted || activeGameId.current !== id) return;
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(log, null, 2)], { type: "application/json" }),
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `2048-${id}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      if (!controller.signal.aborted && activeGameId.current === id) {
        setMessage(
          error instanceof Error ? error.message : "History export failed.",
        );
      }
    } finally {
      releaseController(controller);
    }
  }, [gameId, createController, releaseController]);

  const dismissMessage = useCallback(() => setMessage(""), []);

  return {
    gameId,
    game,
    seed,
    history,
    message,
    isBusy,
    lastMove,
    applyState,
    applyObservedState,
    applyMoveResult,
    move,
    createGame,
    setControl,
    share,
    exportHistory,
    dismissMessage,
  };
}
