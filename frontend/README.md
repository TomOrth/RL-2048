# Frontend architecture

`App.tsx` is the composition root. It connects the session hook to the board workspace and inspector without owning domain state.

- `hooks/useGameSession.ts` owns the selected game, authoritative revisions, human moves, controller changes, history, exports, and session polling. It guards responses by game ID, aborts requests on cleanup, and resumes polling when the page becomes visible.
- `hooks/useModelConnection.ts` owns model settings drafts, key-preservation and explicit key clearing, connection status, and check/step/run/pause actions. `ModelConnection` is keyed by game ID so credentials and drafts are discarded when attaching to another session.
- `components/Board.tsx` renders backend board state and consumes backend move transitions for animation. It contains no game rules.
- `components/GamePanel.tsx` composes the board, score, session message, and `GameControls.tsx`.
- `components/ControllerPanel.tsx` selects human, external, and built-in control, including pause and takeover.
- `components/SessionDetails.tsx` shows session metadata and exposes share, API-link, and export actions.
- `components/ModelConnection.tsx` renders the model configuration and controls. `components/MoveInspector.tsx` renders legal moves and recent history.

The refactor follows these Vercel rules: `state-decouple-implementation`, `patterns-children-over-render-props`, `rerender-use-ref-transient-values`, `rerender-derived-state-no-effect`, `rerender-move-effect-to-event`, `client-event-listeners`, and `async-parallel`. The game board and revision remain authoritative on the server; hooks coordinate transport and components render explicit data and actions.
