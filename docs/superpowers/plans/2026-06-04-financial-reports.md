# Financial Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic financial statement and annual-report access to the stock analysis page.

**Architecture:** Keep AkShare and upstream field quirks inside a new backend service. Expose a narrow JSON contract with summarized metrics, statement rows, and CNInfo disclosure links, then render it as stock-analysis tabs in the existing React page. AI interpretation remains optional later; the baseline feature must work without an LLM.

**Tech Stack:** FastAPI, Pydantic, pandas, AkShare, React 19, TanStack Query, Mantine 9.

---

### Task 1: Backend Financial Service Contract

**Files:**
- Create: `backend/app/services/financials.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_core.py`

- [ ] **Step 1: Write the failing test**

Add a test with a small fake financial provider. It should call `run_stock_financials(provider, "001270", years=2)` and assert:
- `code == "001270"`
- statement rows include `report_date`, `revenue`, `net_profit`, `operating_cash_flow`, `asset_liability_ratio`
- `summary["latest_report_date"]` is the newest report date
- disclosure rows keep `title`, `publish_date`, and `url`

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_core.py::test_stock_financials_builds_summary_from_provider -q`
Expected: FAIL because `app.services.financials` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create `financials.py` with:
- provider protocol methods for financial report, indicator, and disclosure data
- AkShare-backed provider wrapper functions
- `run_stock_financials(provider, symbol, years=5, refresh=False)` returning a narrow dict
- numeric coercion helpers that tolerate missing AkShare columns

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/python -m pytest backend/tests/test_core.py::test_stock_financials_builds_summary_from_provider -q`
Expected: PASS.

### Task 2: FastAPI Endpoint

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_core.py`

- [ ] **Step 1: Write the failing test**

Add a route-level test using monkeypatch to replace the financial provider and call `main.stock_financials("001270", years=2)`. Assert the response model contains `code`, `statements`, `indicators`, `disclosures`, and `summary`.

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_core.py::test_stock_financials_api_returns_response_model -q`
Expected: FAIL because the endpoint does not exist.

- [ ] **Step 3: Write minimal implementation**

Add:
- `StockFinancialsResponse` Pydantic model
- `GET /api/stock-financials?symbol=001270&years=5&refresh=false`
- thin route that calls `run_stock_financials`.

- [ ] **Step 4: Run backend tests**

Run: `./.venv/bin/python -m pytest backend/tests -q`
Expected: PASS.

### Task 3: Frontend API and Stock Page UI

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add TypeScript contract**

Add `StockFinancialsResponse`, `FinancialStatementRow`, `FinancialIndicatorRow`, and `DisclosureReport` types plus `fetchStockFinancials`.

- [ ] **Step 2: Render financial tabs**

On `StockAnalysisPage`, when an analysis exists:
- fetch `/api/stock-financials` by `analysis.code`
- show tabs/cards for `财务概览`, `三大报表`, and `公告年报`
- show annual report links with `target="_blank"` and full `title` tooltips
- keep empty/error states visible and compact.

- [ ] **Step 3: Build verify**

Run: `npm --prefix frontend run build`
Expected: PASS.

### Task 4: End-to-End Verification

**Files:**
- No source edits unless verification reveals a defect.

- [ ] **Step 1: Run full test suite**

Run: `npm run test`
Expected: backend pytest and frontend build pass.

- [ ] **Step 2: Browser verify**

Open `http://localhost:5173/stock` or `http://10.95.164.91:5173/stock`, search `001270`, run analysis, and confirm:
- financial section loads after stock analysis
- statement metrics are readable on desktop and narrower widths
- annual report links are clickable
- no console errors.

- [ ] **Step 3: Commit feature**

Commit with Lore trailers recording AkShare/CNInfo constraints and verification evidence.
