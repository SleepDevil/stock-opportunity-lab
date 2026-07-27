# Self-Evolving Stock Lab Design

## Purpose

Stock Opportunity Lab already scans A-share candidates and validates next-day plans with backtests. The missing core loop is durable learning: every recommendation should leave behind an outcome record, a short attribution, and strategy evidence that future scans and explanations can read.

## First-Stage Scope

This stage builds a local learning memory MVP:

- Backtests automatically persist per-stock learning records under `data/learning/`.
- The persisted records include recommendation date, validation date, entry outcome, return, drawdown, system attribution, and feature snapshot.
- A learning summary tracks total cases, buy cases, win rate, average return, recurring failure reasons, recurring success reasons, and recent records.
- Users can add their own post-mortem note for a validated recommendation. The note is stored next to the system attribution and appears in future learning summaries.
- AI payloads for scans and backtests include the learning summary, so deterministic or external AI explanations can use prior evidence instead of treating every day as isolated.
- Future candidates are annotated with historical learning signals when their board and tags resemble prior records.
- The system produces conservative strategy-optimization suggestions as paper experiments instead of silently changing live parameters.
- A dedicated self-review cycle can select the latest prior screen report for a chosen actual date, run the backtest, persist learning records, and return strategy-optimization evidence in one response.

## Non-Goals

- Do not promise or hardcode 80% accuracy. The system should measure progress toward that target and expose whether it is improving.
- Do not add a new market-data provider or new dependency.
- Do not auto-trade or connect to brokerage accounts.
- Do not rewrite the existing screener. This stage adds feedback memory around it.

## Backend Shape

Create `backend/app/services/learning.py` as the single owner of the learning store. It should expose:

- `build_learning_record(row, screen_date, actual_date)`: converts a backtest row into a stable record.
- `persist_backtest_learning(config, screen_date, actual_date, rows, summary)`: writes records and updates summary.
- `load_learning_summary(config, limit=20)`: reads aggregate learning state for API responses and AI payloads.
- `append_user_feedback(config, request)`: appends a user note to the matching stock/date record and refreshes summary.
- `annotate_candidates_with_learning(config, candidates)`: adds historical learning hints to later screen output.

The storage format stays simple JSON:

- `data/learning/records.json`
- `data/learning/summary.json`

Records are keyed by `screen_date:actual_date:code`, making repeated backtests idempotent while preserving user notes.

Create `backend/app/services/strategy_optimizer.py` to translate learning evidence into explicit parameter experiment proposals. The optimizer compares the current strategy with a proposed strategy and only emits conservative, reviewable changes such as tighter stop loss, lower per-trade risk, or a small entry-premium adjustment when the stored samples support it.

Create `backend/app/services/evolution.py` as the orchestration owner for one self-review cycle. It should not duplicate backtest or optimizer logic; it resolves the screen date, calls `run_backtest`, then calls `build_strategy_optimization`.

## API Shape

Add models:

- `LearningRecord`
- `LearningSummary`
- `LearningFeedbackRequest`
- `LearningFeedbackResponse`

Add endpoints:

- `GET /api/learning-summary`
- `POST /api/learning-feedback`
- `GET /api/strategy-optimization`
- `POST /api/evolution-cycle`

Also extend `BacktestResponse` with `learning_summary` and make `/api/backtest` return the refreshed summary after every run.

The strategy-optimization response includes `target_win_rate`, current metrics, current strategy, proposed strategy, parameter changes, an experiment plan, and a disclaimer that the recommendation is paper-only.

The evolution-cycle response includes the resolved screen date, actual date, nested backtest response, refreshed learning summary, strategy optimization response, and a human-readable run message.

## Frontend Shape

Keep the UI focused on the existing Backtest Lab. Add one panel below the backtest table:

- Shows learning coverage, buy win rate, average return, top failure reasons, and top success reasons.
- Shows a compact list of recent learning records.
- Lets the user select a stock from the latest backtest and submit a note. The note becomes part of the local learning memory.
- Shows parameter experiment suggestions with current/proposed values and confidence.
- Provides a self-review action that runs the evolution cycle and refreshes the current backtest, learning summary, and parameter experiment suggestions.

The candidate table also surfaces historical learning signals inline so the main opportunity workflow can see whether similar past setups were profitable, risky, or under-sampled.

## Testing

Backend tests should lock the core behavior first:

- A backtest writes learning records and returns a learning summary.
- User feedback appends to the matching learning record and appears in later summaries.
- AI payloads include learning memory when available.
- Candidate screening annotates rows with historical learning memory.
- Strategy optimizer proposes conservative parameter experiments from stored outcomes.
- Evolution cycle picks the latest prior screen report and returns both backtest and optimizer evidence.

Frontend verification is the existing TypeScript build.
