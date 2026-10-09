import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  GameState,
  LLMSettings,
  LLMSettingsResponse,
  LLMStatus,
  MoveResult,
} from "../api/types";

const DEFAULT_SETTINGS: LLMSettings = {
  url: "http://localhost:8001/v1",
  model: "",
  api_key: null,
  max_tokens: 64,
  token_limit_field: "max_completion_tokens",
  timeout_seconds: 30,
  delay_seconds: 0.4,
};

export interface ModelSessionPort {
  gameId: string | null;
  game: GameState | null;
  applyObservedState: (next: GameState) => void;
  applyMoveResult: (result: MoveResult) => void;
  setControl: (
    mode: "human" | "external" | "builtin",
    paused?: boolean,
    signal?: AbortSignal,
  ) => Promise<GameState | null>;
}

export interface ModelConnection {
  settings: LLMSettings;
  savedSettings: LLMSettingsResponse | null;
  status: LLMStatus | null;
  message: string;
  isBusy: boolean;
  clearKeyRequested: boolean;
  updateSettings: (patch: Partial<LLMSettings>) => void;
  clearSavedKey: () => void;
  saveSettings: () => Promise<void>;
  checkConnection: () => Promise<void>;
  step: () => Promise<void>;
  runOrPause: () => Promise<void>;
  dismissMessage: () => void;
}

export function useModelConnection(session: ModelSessionPort): ModelConnection {
  const { game, gameId, applyObservedState, applyMoveResult, setControl } =
    session;
  const hasGame = game !== null;
  const gameMode = game?.control.mode;
  const [settings, setSettings] = useState<LLMSettings>({
    ...DEFAULT_SETTINGS,
  });
  const [savedSettings, setSavedSettings] =
    useState<LLMSettingsResponse | null>(null);
  const [status, setStatus] = useState<LLMStatus | null>(null);
  const [message, setMessage] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [clearKeyRequested, setClearKeyRequested] = useState(false);
  const mounted = useRef(false);
  const controllers = useRef(new Set<AbortController>());
  const activeGameId = useRef(gameId);
  const settingsWereEdited = useRef(false);

  const makeController = useCallback(() => {
    const controller = new AbortController();
    controllers.current.add(controller);
    return controller;
  }, []);
  const releaseController = useCallback((controller: AbortController) => {
    controllers.current.delete(controller);
  }, []);

  useEffect(() => {
    const pendingControllers = controllers.current;
    mounted.current = true;
    return () => {
      mounted.current = false;
      pendingControllers.forEach((controller) => controller.abort());
      pendingControllers.clear();
    };
  }, []);

  useEffect(() => {
    activeGameId.current = gameId;
    if (!gameId) return;

    const controller = makeController();
    void Promise.allSettled([
      api.settings(gameId, controller.signal),
      api.llmStatus(gameId, controller.signal),
    ])
      .then(([settingsResult, statusResult]) => {
        if (controller.signal.aborted || activeGameId.current !== gameId)
          return;
        if (settingsResult.status === "fulfilled") {
          const saved = settingsResult.value;
          setSavedSettings(saved);
          if (!settingsWereEdited.current) {
            setSettings({
              url: saved.url,
              model: saved.model,
              api_key: null,
              max_tokens: saved.max_tokens,
              token_limit_field: saved.token_limit_field,
              timeout_seconds: saved.timeout_seconds,
              delay_seconds: saved.delay_seconds,
            });
          }
        }
        if (statusResult.status === "fulfilled") setStatus(statusResult.value);
      })
      .finally(() => releaseController(controller));

    return () => controller.abort();
  }, [gameId, makeController, releaseController]);

  useEffect(() => {
    if (!gameId) return;
    let stopped = false;
    let inFlight = false;
    let timer = 0;
    let controller: AbortController | null = null;

    const poll = async () => {
      if (stopped || inFlight || document.hidden) return;
      inFlight = true;
      controller = makeController();
      try {
        const nextStatus = await api.llmStatus(gameId, controller.signal);
        if (
          !stopped &&
          !controller.signal.aborted &&
          activeGameId.current === gameId
        )
          setStatus(nextStatus);
      } catch {
        // The main session polling owns connection errors; status can recover on its next refresh.
      } finally {
        inFlight = false;
        if (controller) releaseController(controller);
        controller = null;
        if (!stopped && !document.hidden) timer = window.setTimeout(poll, 1000);
      }
    };

    const onVisibilityChange = () => {
      window.clearTimeout(timer);
      if (document.hidden) controller?.abort();
      else if (!inFlight && !stopped) timer = window.setTimeout(poll, 0);
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    if (!document.hidden) timer = window.setTimeout(poll, 1000);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [gameId, makeController, releaseController]);

  const updateSettings = useCallback((patch: Partial<LLMSettings>) => {
    settingsWereEdited.current = true;
    setSettings((current) => ({ ...current, ...patch }));
    if (Object.prototype.hasOwnProperty.call(patch, "api_key"))
      setClearKeyRequested(false);
  }, []);

  const clearSavedKey = useCallback(() => {
    settingsWereEdited.current = true;
    setSettings((current) => ({ ...current, api_key: "" }));
    setClearKeyRequested(true);
  }, []);

  const saveSettings = useCallback(async () => {
    if (!gameId) return;
    const id = gameId;
    const controller = makeController();
    try {
      const saved = await api.saveSettings(
        id,
        {
          ...settings,
          api_key: clearKeyRequested ? "" : settings.api_key || null,
        },
        controller.signal,
      );
      if (!controller.signal.aborted && activeGameId.current === id) {
        setSavedSettings(saved);
        setSettings((current) => ({ ...current, api_key: null }));
        setClearKeyRequested(false);
        setMessage("Model settings saved.");
      }
    } catch (error) {
      if (!controller.signal.aborted && activeGameId.current === id) {
        setMessage(
          error instanceof Error
            ? error.message
            : "Settings could not be saved.",
        );
      }
    } finally {
      releaseController(controller);
    }
  }, [gameId, settings, clearKeyRequested, makeController, releaseController]);

  const perform = useCallback(
    async (action: "check" | "step" | "run" | "pause") => {
      if (!gameId || !hasGame) return;
      const id = gameId;
      const controller = makeController();
      if (action !== "pause") setIsBusy(true);
      setMessage("");
      try {
        if (action === "check") {
          const result = await api.check(id, controller.signal);
          if (!controller.signal.aborted && activeGameId.current === id) {
            setMessage(
              result.ok
                ? `Connection ready · ${Math.round(result.latency_ms)} ms`
                : result.content,
            );
          }
        }

        if (action === "run" || action === "step") {
          if (gameMode !== "builtin") {
            const controlled = await setControl(
              "builtin",
              false,
              controller.signal,
            );
            if (
              !controlled ||
              controller.signal.aborted ||
              activeGameId.current !== id
            )
              return;
          }
          if (action === "step") {
            const result = await api.step(id, controller.signal);
            if (!controller.signal.aborted && activeGameId.current === id)
              applyMoveResult(result);
          } else {
            const nextStatus = await api.run(id, controller.signal);
            if (!controller.signal.aborted && activeGameId.current === id)
              setStatus(nextStatus);
          }
        }

        if (action === "pause") {
          const nextStatus = await api.pause(id, controller.signal);
          if (!controller.signal.aborted && activeGameId.current === id)
            setStatus(nextStatus);
        }
      } catch (error) {
        if (!controller.signal.aborted && activeGameId.current === id) {
          setMessage(
            error instanceof Error ? error.message : "Model request failed.",
          );
        }
      } finally {
        releaseController(controller);
        if (mounted.current && activeGameId.current === id) {
          if (action !== "pause") setIsBusy(false);
          const refreshController = makeController();
          try {
            const [next, nextStatus] = await Promise.all([
              api.state(id, refreshController.signal),
              api.llmStatus(id, refreshController.signal).catch(() => null),
            ]);
            if (
              !refreshController.signal.aborted &&
              mounted.current &&
              activeGameId.current === id
            ) {
              applyObservedState(next);
              if (nextStatus) setStatus(nextStatus);
            }
          } catch {
            // Preserve the action result or error already displayed to the user.
          } finally {
            releaseController(refreshController);
          }
        }
      }
    },
    [
      gameId,
      hasGame,
      gameMode,
      applyObservedState,
      applyMoveResult,
      setControl,
      makeController,
      releaseController,
    ],
  );

  const checkConnection = useCallback(() => perform("check"), [perform]);
  const step = useCallback(() => perform("step"), [perform]);
  const runOrPause = useCallback(
    () => perform(status?.running ? "pause" : "run"),
    [perform, status?.running],
  );
  const dismissMessage = useCallback(() => setMessage(""), []);

  return {
    settings,
    savedSettings,
    status,
    message,
    isBusy,
    clearKeyRequested,
    updateSettings,
    clearSavedKey,
    saveSettings,
    checkConnection,
    step,
    runOrPause,
    dismissMessage,
  };
}
