export type Direction = "up" | "down" | "left" | "right";
export type ControlMode = "human" | "external" | "builtin";
export interface GameState {
  id: string;
  revision: number;
  board: number[][];
  score: number;
  max_tile: number;
  legal_moves: Direction[];
  status: "ongoing" | "game_over";
  reached_2048: boolean;
  move_count: number;
  control: { mode: ControlMode; paused: boolean };
}
export interface CreateGameResponse {
  state: GameState;
  seed: number;
}
export interface MoveResult {
  state: GameState;
  moved: boolean;
  score_delta: number;
  spawned_tile: { row: number; column: number; value: number } | null;
  transitions: {
    from_row: number;
    from_column: number;
    to_row: number;
    to_column: number;
    value: number;
    merged: boolean;
  }[];
}
export interface HistoryMove {
  timestamp: string;
  source: ControlMode;
  direction: Direction;
  moved: boolean;
  board_before: number[][];
  board_after: number[][];
  score_delta: number;
  spawned_tile: MoveResult["spawned_tile"];
  revision_before: number;
  revision_after: number;
}
export interface GameHistory {
  schema_version: number;
  game_id: string;
  seed: number;
  initial_board: number[][];
  moves: HistoryMove[];
  final_state: GameState;
}
export interface LLMSettings {
  url: string;
  model: string;
  api_key?: string | null;
  max_tokens: number;
  token_limit_field: "max_completion_tokens" | "max_tokens";
  timeout_seconds: number;
  delay_seconds: number;
}
export interface LLMSettingsResponse extends Omit<LLMSettings, "api_key"> {
  resolved_url: string;
  api_key_configured: boolean;
}
export interface LLMStatus {
  configured: boolean;
  running: boolean;
  busy: boolean;
  error: string | null;
  last_response: string | null;
  last_action: Direction | null;
  last_latency_ms: number | null;
}
export interface LLMCheckResponse {
  ok: boolean;
  content: string;
  latency_ms: number;
}
