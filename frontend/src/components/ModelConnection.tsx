import type { LLMSettings } from "../api/types";
import {
  useModelConnection,
  type ModelSessionPort,
} from "../hooks/useModelConnection";

export function ModelConnection({ session }: { session: ModelSessionPort }) {
  const model = useModelConnection(session);
  const settings = model.settings;
  const setSettings = (patch: Partial<LLMSettings>) =>
    model.updateSettings(patch);
  const statusLabel = model.status?.running
    ? "RUNNING"
    : model.savedSettings
      ? "READY"
      : "SETUP";

  return (
    <section className="inspect-section model-section">
      <div className="section-title">
        <h2>Model connection</h2>
        <span
          className={`connection ${model.savedSettings?.api_key_configured ? "configured" : ""}`}
        >
          {statusLabel}
        </span>
      </div>
      <label className="field">
        Server URL
        <input
          value={settings.url}
          onChange={(event) => setSettings({ url: event.target.value })}
          placeholder="http://localhost:8001/v1"
        />
      </label>
      <label className="field">
        Model name
        <input
          value={settings.model}
          onChange={(event) => setSettings({ model: event.target.value })}
          placeholder="e.g. gpt-4.1-mini"
        />
      </label>
      <label className="field">
        API key{" "}
        <span className="optional">
          {model.savedSettings?.api_key_configured
            ? "configured · leave blank to keep"
            : "optional"}
        </span>
        <input
          type="password"
          value={settings.api_key ?? ""}
          onChange={(event) => setSettings({ api_key: event.target.value })}
          placeholder={
            model.savedSettings?.api_key_configured ? "••••••••••••" : "No key"
          }
          autoComplete="new-password"
        />
      </label>
      <div className="field-grid">
        <label className="field">
          Token limit
          <input
            type="number"
            min="1"
            max="32768"
            value={settings.max_tokens}
            onChange={(event) =>
              setSettings({ max_tokens: Number(event.target.value) })
            }
          />
        </label>
        <label className="field">
          Timeout · sec
          <input
            type="number"
            min="1"
            max="300"
            value={settings.timeout_seconds}
            onChange={(event) =>
              setSettings({ timeout_seconds: Number(event.target.value) })
            }
          />
        </label>
      </div>
      <div className="field-grid">
        <label className="field">
          Token field
          <select
            value={settings.token_limit_field}
            onChange={(event) =>
              setSettings({
                token_limit_field: event.target
                  .value as LLMSettings["token_limit_field"],
              })
            }
          >
            <option value="max_completion_tokens">Modern</option>
            <option value="max_tokens">Legacy</option>
          </select>
        </label>
        <label className="field">
          Move delay · sec
          <input
            type="number"
            min="0"
            max="60"
            step="0.1"
            value={settings.delay_seconds}
            onChange={(event) =>
              setSettings({ delay_seconds: Number(event.target.value) })
            }
          />
        </label>
      </div>
      {model.savedSettings?.resolved_url && (
        <p className="resolved-url">POST {model.savedSettings.resolved_url}</p>
      )}
      <div className="model-actions">
        <button
          className="quiet-button"
          onClick={() => void model.saveSettings()}
          disabled={!session.gameId || model.isBusy}
        >
          Save settings
        </button>
        <button
          className="quiet-button"
          onClick={() => void model.checkConnection()}
          disabled={!session.gameId || model.isBusy}
        >
          Check
        </button>
      </div>
      {model.savedSettings?.api_key_configured && (
        <button className="clear-key" onClick={model.clearSavedKey}>
          Clear saved API key
        </button>
      )}
      <div className="run-actions">
        <button
          onClick={() => void model.step()}
          disabled={!session.game || model.isBusy}
        >
          One move
        </button>
        <button
          className="run-button"
          onClick={() => void model.runOrPause()}
          disabled={!session.game || (model.isBusy && !model.status?.running)}
        >
          {model.status?.running ? "Pause" : "Run model"}{" "}
          <span>{model.status?.running ? "Ⅱ" : "▶"}</span>
        </button>
      </div>
      {model.message && (
        <div className="notice model-notice" role="status">
          <span>{model.message}</span>
          <button onClick={model.dismissMessage} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
      {model.status?.error && (
        <p className="model-error">{model.status.error}</p>
      )}
      {model.status?.last_action && (
        <p className="last-action">
          Last choice <b>{model.status.last_action}</b>
          {model.status.last_latency_ms != null &&
            ` · ${Math.round(model.status.last_latency_ms)} ms`}
        </p>
      )}
    </section>
  );
}
