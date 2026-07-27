# Self-Evolving Stock Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable learning loop so backtest outcomes, user post-mortems, candidate annotations, automatic self-review cycles, and conservative strategy experiments become reusable evidence for later stock analysis.

**Architecture:** Keep the current scanner and backtester intact. Add a focused backend learning store, include its summary in API responses and AI payloads, annotate future candidates with historical evidence, expose both learning state and paper-only parameter experiments inside the existing Backtest Lab page, then add a dedicated evolution cycle that can replay the latest prior recommendation set against a chosen actual date.

**Tech Stack:** FastAPI, Pydantic, pandas, JSON files under `data/`, React 19, TanStack Query, Mantine 9.

---

### Task 1: Backend Learning Store

**Files:**
- Create: `backend/app/services/learning.py`
- Modify: `backend/tests/test_core.py`

- [x] Write tests proving a backtest creates `data/learning/records.json` and `data/learning/summary.json`.
- [x] Implement stable record keys with `screen_date:actual_date:code`.
- [x] Derive deterministic system attribution from entry outcome, return, drawdown, stop-loss touch, take-profit touch, and price-plan fields.
- [x] Keep repeated backtests idempotent while preserving any user notes already attached to the same record.

### Task 2: API and AI Payload Integration

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/ai.py`
- Modify: `backend/tests/test_core.py`

- [x] Extend `BacktestResponse` with `learning_summary`.
- [x] Add `GET /api/learning-summary`.
- [x] Add `POST /api/learning-feedback`.
- [x] Include `learning_summary` in `build_payload` when available.
- [x] Update deterministic explanations to mention the current strategy memory.

### Task 3: Frontend Learning Panel

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [x] Add frontend types for learning records and summaries.
- [x] Add API helpers for learning summary and feedback.
- [x] Add a Backtest Lab panel that displays learning metrics, reasons, recent records, and a feedback form.
- [x] Refresh the learning summary after submitting feedback.

### Task 4: Candidate Learning Signals and Strategy Optimizer

**Files:**
- Modify: `backend/app/services/learning.py`
- Create: `backend/app/services/strategy_optimizer.py`
- Modify: `backend/app/services/screener.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/CandidateTable.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `backend/tests/test_core.py`

- [x] Annotate screened candidates with historical sample count, win rate, average return, recommended learning action, and learning hint.
- [x] Add `GET /api/strategy-optimization` with current metrics, current strategy, proposed strategy, parameter changes, and paper experiment plan.
- [x] Keep optimization suggestions conservative and non-mutating; they do not rewrite strategy config automatically.
- [x] Show candidate learning badges in the opportunity table.
- [x] Show parameter experiment suggestions in the strategy-evolution panel.

### Task 5: Automatic Self-Review Cycle

**Files:**
- Create: `backend/app/services/evolution.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_core.py`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/App.tsx`

- [x] Add backend tests proving the cycle selects the latest prior screen report for an actual date.
- [x] Add `POST /api/evolution-cycle` returning a nested backtest response, refreshed learning summary, and strategy optimization response.
- [x] Keep the orchestration thin by reusing `run_backtest` and `build_strategy_optimization`.
- [x] Add a Backtest Lab self-review action that refreshes backtest state, learning summary, and parameter suggestions.

### Task 6: Verification

**Files:**
- No source edits unless verification finds a defect.

- [x] Run the targeted backend tests while developing.
- [x] Run `./.venv/bin/python -m pytest backend/tests -q`.
- [x] Run `npm --prefix frontend run build`.
- [x] Run `npm run test`.
- [x] Browser-verify the Backtest Lab and home opportunity screen.
- [x] Report the implementation boundary and remaining risks, especially that 80% sustained win rate requires accumulated validated samples rather than a code guarantee.
