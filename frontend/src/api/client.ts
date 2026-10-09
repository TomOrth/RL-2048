import type {
  CreateGameResponse,
  Direction,
  GameHistory,
  GameState,
  LLMCheckResponse,
  LLMSettings,
  LLMSettingsResponse,
  LLMStatus,
  MoveResult,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      /* Keep the HTTP status message. */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
const json = (body: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(body),
});
const withSignal = (signal?: AbortSignal): RequestInit =>
  signal ? { signal } : {};

export const api = {
  create: (seed?: number, signal?: AbortSignal) =>
    request<CreateGameResponse>("/games", {
      ...json(seed === undefined ? {} : { seed }),
      ...withSignal(signal),
    }),
  state: (id: string, signal?: AbortSignal) =>
    request<GameState>(`/games/${encodeURIComponent(id)}`, withSignal(signal)),
  move: (
    id: string,
    direction: Direction,
    revision: number,
    signal?: AbortSignal,
  ) =>
    request<MoveResult>(`/games/${encodeURIComponent(id)}/moves`, {
      ...json({ direction, expected_revision: revision, source: "human" }),
      ...withSignal(signal),
    }),
  control: (
    id: string,
    mode: "human" | "external" | "builtin",
    paused: boolean,
    revision: number,
    signal?: AbortSignal,
  ) =>
    request<GameState>(`/games/${encodeURIComponent(id)}/control`, {
      method: "PUT",
      body: JSON.stringify({ mode, paused, expected_revision: revision }),
      ...withSignal(signal),
    }),
  history: (id: string, signal?: AbortSignal) =>
    request<GameHistory>(
      `/games/${encodeURIComponent(id)}/history`,
      withSignal(signal),
    ),
  settings: (id: string, signal?: AbortSignal) =>
    request<LLMSettingsResponse>(
      `/games/${encodeURIComponent(id)}/llm/settings`,
      withSignal(signal),
    ),
  saveSettings: (id: string, settings: LLMSettings, signal?: AbortSignal) =>
    request<LLMSettingsResponse>(
      `/games/${encodeURIComponent(id)}/llm/settings`,
      { method: "PUT", body: JSON.stringify(settings), ...withSignal(signal) },
    ),
  llmStatus: (id: string, signal?: AbortSignal) =>
    request<LLMStatus>(
      `/games/${encodeURIComponent(id)}/llm/status`,
      withSignal(signal),
    ),
  check: (id: string, signal?: AbortSignal) =>
    request<LLMCheckResponse>(`/games/${encodeURIComponent(id)}/llm/check`, {
      ...json({}),
      ...withSignal(signal),
    }),
  step: (id: string, signal?: AbortSignal) =>
    request<MoveResult>(`/games/${encodeURIComponent(id)}/llm/step`, {
      ...json({}),
      ...withSignal(signal),
    }),
  run: (id: string, signal?: AbortSignal) =>
    request<LLMStatus>(`/games/${encodeURIComponent(id)}/llm/run`, {
      ...json({}),
      ...withSignal(signal),
    }),
  pause: (id: string, signal?: AbortSignal) =>
    request<LLMStatus>(`/games/${encodeURIComponent(id)}/llm/pause`, {
      ...json({}),
      ...withSignal(signal),
    }),
};
