# Structured model moves

Replace the built-in connector's one-word completion format with a strict JSON object, for example `{"direction":"left"}`. This applies to the shared inference path used by Check, One move, and Run; game HTTP request and response contracts remain stable.

## Implementation

1. Define a Pydantic v2 response model with a required `direction` field using the existing Direction literal. Forbid extra fields and validate strictly. Declare Pydantic as a direct dependency because this connector uses it directly.
2. Derive an OpenAI-compatible `response_format` from the model's JSON schema: `type: json_schema`, a named schema, `strict: true`, required direction, and `additionalProperties: false`. Restrict the direction enum to the legal moves for that request without mutating shared schema state.
3. Keep the existing async HTTP transport and endpoint resolution. The OpenAI SDK is optional for this protocol; adding it is unnecessary unless a concrete need emerges. Preserve the token field choice, authentication, timeouts, logging, cancellation, and revision checks. Do not change the user's token settings or restart the live backend.
4. Update the system prompt to request JSON and remove contradictory one-word instructions. Preserve its gameplay guidance. Parse the entire content as the response model; reject prose, fences, missing or extra fields, wrong types, invalid directions, and illegal moves. Do not silently fall back to text, JSON mode, or retry failed requests.
5. Make Check send a valid representative board with matching legal moves, rather than an empty board incorrectly labeled as having four legal moves. It must not move or mutate the user's game.
6. Keep last_action as the parsed direction and last_response/check content as valid JSON text. The frontend requires no change.
7. Report HTTP 400/422 with a safe hint that the server may reject the schema or another request parameter. Do not assert a specific cause without evidence or expose raw upstream bodies/credentials. Replace the temporary full-body INFO log with metadata diagnostics so validation failures cannot log sensitive upstream data.

## Verification and documentation

Adapt existing mocked completion fixtures to JSON, preserving intentional invalid cases. Verify exact wire schema and legal-move enum (including a single legal move), strict parsing, no state change during Check, step/run success, stale response and cancellation behavior, refusals, truncation, unsupported-schema errors, credential redaction, token field selection, and custom/full endpoint URLs. Run the complete backend suite. Document the JSON contract and model-server requirement in README and API docs. No mobile or visual frontend testing is needed.

The user confirmed vLLM as the serving stack. Its documentation supports the planned `response_format: json_schema` request with Pydantic-generated schemas. Real constrained decoding still depends on the installed version and serving configuration. Local validation detects unsupported or ignored constraints but cannot enforce token generation itself. Live Qwen verification remains dependent on the user's configured model. vLLM also documents a specific Qwen3 Coder reasoning caveat; do not assume it applies to every Qwen model or change the server's reasoning configuration automatically.

Reference: [OpenAI structured outputs for Chat Completions](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat).

Server reference: [vLLM structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/).
