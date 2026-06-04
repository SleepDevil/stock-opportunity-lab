# Stock Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add deterministic stock intelligence feeds for individual stock announcements, news, and Dragon Tiger List data.

**Architecture:** Put all AkShare/EastMoney field handling in a focused backend service, expose one `/api/stock-intelligence` endpoint, and render the result inside the existing stock analysis page as tabs. The endpoint returns structured data first; any AI interpretation can be added later on top of the same contract.

**Tech Stack:** FastAPI, Pydantic, pandas, AkShare, React 19, TanStack Query, Mantine 9.

---

### Task 1: Backend Service Contract

**Files:**
- Create: `backend/app/services/stock_intelligence.py`
- Modify: `backend/tests/test_core.py`

- [x] **Step 1: Write the failing test**

Add `test_stock_intelligence_combines_notices_news_and_lhb` with a fake provider exposing:
`notices(symbol, begin_date, end_date)`, `news(symbol)`, `lhb_dates(symbol)`, `lhb_detail(symbol, date, flag)`, `lhb_daily(start_date, end_date)`, and `lhb_institution_stats(start_date, end_date)`.

The expected result:
- `code == "001309"`
- notices include `title`, `category`, `publish_date`, `source`, `url`
- news include `title`, `content`, `publish_time`, `source`, `url`
- dragon tiger summary includes close price, turnover, reason, total amount, net buy amount, institution buy/sell/net amount
- buy and sell seats are normalized into stable fields.

- [x] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_core.py::test_stock_intelligence_combines_notices_news_and_lhb -q`
Expected: FAIL because `app.services.stock_intelligence` does not exist.

- [x] **Step 3: Implement minimal service**

Create `stock_intelligence.py` with:
- `AkShareStockIntelligenceProvider`
- `run_stock_intelligence(provider, symbol, trade_date, notice_forward_days=1, news_limit=20)`
- normalizers for notices, news, Dragon Tiger summary, institution stats, and buy/sell seats.

- [x] **Step 4: Run service test**

Run: `./.venv/bin/python -m pytest backend/tests/test_core.py::test_stock_intelligence_combines_notices_news_and_lhb -q`
Expected: PASS.

### Task 2: API Route

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_core.py`

- [x] **Step 1: Write the failing API test**

Add `test_stock_intelligence_api_returns_response_model`, monkeypatching `main.stock_intelligence_provider` and `main.run_stock_intelligence`, then call `main.stock_intelligence("001309", date="20260604", refresh=True)`.

- [x] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/python -m pytest backend/tests/test_core.py::test_stock_intelligence_api_returns_response_model -q`
Expected: FAIL because route function is missing.

- [x] **Step 3: Implement route**

Add `StockIntelligenceResponse` and `GET /api/stock-intelligence`.

- [x] **Step 4: Run backend tests**

Run: `./.venv/bin/python -m pytest backend/tests -q`
Expected: PASS.

### Task 3: Frontend Stock Page

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [x] **Step 1: Add frontend types and request function**

Add `StockIntelligenceResponse` and `fetchStockIntelligence`.

- [x] **Step 2: Render intelligence tabs**

In `StockAnalysisPage`, fetch intelligence after stock analysis succeeds. Render `公告`, `新闻`, and `龙虎榜` tabs with compact cards and table rows. Links open in a new tab and long titles keep tooltips.

- [x] **Step 3: Build frontend**

Run: `npm --prefix frontend run build`
Expected: PASS.

### Task 4: Verification and Commit

**Files:**
- No source edits unless verification finds a defect.

- [x] **Step 1: Run full tests**

Run: `npm run test`
Expected: backend pytest and frontend build pass.

- [x] **Step 2: Browser verify**

Open `http://10.95.164.91:5173/stock`, analyze `001309`, and confirm finance plus intelligence tabs render announcement, news, and Dragon Tiger List data without console errors.

- [x] **Step 3: Commit**

Commit with Lore trailers recording AkShare/EastMoney constraints and verification evidence.
