# Google Stitch Prompt: Stock Opportunity Lab

Use this prompt to generate a high-fidelity desktop web app design for Stock Opportunity Lab.

```text
Design a polished desktop web app called "Stock Opportunity Lab".

Product context:
Stock Opportunity Lab is a local A-share research cockpit for an individual investor. It helps the user run an after-market stock scan, validate the strategy with historical backtests, analyze abnormal news-driven moves, and understand sector fund-flow and market sentiment. It does not connect to brokers and does not place trades.

Design goal:
Create a professional, data-dense, calm quant research dashboard. It should feel like a serious investment research workstation, not a marketing landing page and not a flashy financial TV dashboard.

Visual style:
- Light neutral workspace background.
- Dark navy left navigation and command bar.
- White and very light gray content surfaces with thin borders.
- Accent colors: teal for opportunity / inflow, amber for watch / uncertainty, red for risk / outflow, blue for primary actions.
- Cards should have max 8px border radius.
- Use compact tables, KPI strips, heatmaps, timelines, and chart panels.
- Use line icons similar to lucide icons.
- Use tabular numbers for prices, percentages, amounts, and scores.
- Avoid hero sections, stock photos, decorative gradients, glassmorphism, oversized cards, and marketing copy.

Primary navigation:
1. 今日机会
2. 回测实验室
3. 消息异动
4. 板块资金
5. 策略设置

Generate these screens:

Screen 1: 今日机会 Dashboard
- Left nav with product name and navigation items.
- Top command bar with trade date "2026-06-03", strategy version "固定策略 V1", data source status, refresh button, run scan button.
- Market regime summary at top: state "观察", market breadth, total turnover, limit-up count, limit-down count, sentiment score.
- Sector snapshot panel: top inflow sectors and top outflow sectors.
- Candidate stock table:
  columns: rank, stock name/code, score, price change, turnover amount, turnover rate, volume ratio, sector, opportunity tags, planned low-entry price, planned buy upper bound, high-open abandon price, stop reference.
  sample rows: 华宏科技 002645, 香江控股 600162, 金信诺 300252, 海川智能 300720, 埃斯顿 002747.
- Right rail:
  "今日重点风险" alert cards.
  "消息异动" cards for abnormal stocks.
  "生成报告" export area.
- Keep the page dense but readable.

Screen 2: 个股机会详情
- Header: 华宏科技 002645, score 93.2, sector, risk level, data timestamp.
- Price plan block:
  planned low-entry 32.16, buy upper bound 33.21, breakout confirmation 33.67, high-open abandon 34.30, stop reference 31.01.
- Evidence grid:
  amount 25.38亿, turnover 13.80%, volume ratio 2.34, 60-day strength, float market cap, opportunity tags.
- Mini candlestick/price chart placeholder.
- News/catalyst timeline with source chips and confidence labels.
- Sector relation panel: whether sector fund flow confirms the candidate.
- Historical similar-sample panel: 1-day, 3-day, 5-day outcomes.
- Bottom action buttons: add to watchlist, copy analysis payload, export card.

Screen 3: 回测实验室
- Strategy selector: 固定策略 V1.
- Date range controls, candidate Top N, run backtest button.
- KPI row: sample count, trigger rate, win rate, average return, median return, max drawdown.
- Charts:
  equity curve,
  drawdown curve,
  monthly heatmap,
  return distribution histogram.
- Attribution panels:
  performance by market regime,
  performance by sector,
  performance by turnover-rate bucket,
  performance by volume-ratio bucket.
- Trade detail table with buy mode, simulated buy price, close return, max drawdown, stop/take-profit touched.

Screen 4: 消息异动
- Abnormal move detector dashboard:
  tabs: 跌停, 涨停, 放量长阴, 跳空低开, 炸板, 异常成交额.
- Event list with severity, stock, move type, price change, amount, related sector, event summary, source, confidence.
- Detail panel for an example "东山精密 2026-06-01 跌停":
  show a timeline explaining possible overreaction versus fundamental risk.
  show follow-up performance on 2026-06-02 and 2026-06-03.
  show a label "疑似消息误杀，需要次日量价确认".
- Alert rules panel:
  severe abnormal move + no confirmed fundamental deterioration + sector stabilization + volume confirmation.

Screen 5: 板块资金
- Market state header: 进攻 / 观察 / 防守 segmented control style indicator.
- Sector heatmap with tiles sized by turnover and colored by net inflow/outflow.
- Ranking tables:
  top net inflow,
  top net outflow,
  continuous inflow,
  sudden weakening.
- Sector detail panel:
  breadth,
  momentum,
  turnover,
  candidate count,
  strongest stocks.
- Link candidate stocks to sector confirmation status.

Screen 6: 策略设置
- Show fixed strategy V1 as read-only for now.
- Sections:
  universe filters,
  liquidity filters,
  turnover and volume-ratio filters,
  market-cap filters,
  score weights,
  buy-plan rules,
  risk-budget rules.
- Include disabled "Create custom strategy" and "Save new version" buttons with "coming later" state.

Interaction and states:
- Show loading state for scan and backtest without hiding previous results.
- Show stale-cache status when data is old.
- Show degraded data-source warning when one source fails and fallback is used.
- Show empty states that explain the next action.
- Show error states without stack traces.

Content rules:
- Use Chinese UI copy.
- Avoid unconditional buy language.
- Every recommendation should include a risk or invalidation condition.
- Add a subtle disclaimer: "规则化分析，不构成投资建议".

Responsive note:
Design desktop first at 1440px width. Tablet and mobile variants can stack panels, but the main output should be the desktop research cockpit.
```

## Optional Short Prompt

```text
Create a high-fidelity desktop web app design for a Chinese A-share quant research cockpit named Stock Opportunity Lab. It has five tabs: 今日机会, 回测实验室, 消息异动, 板块资金, 策略设置. The UI should be calm, professional, data-dense, light neutral, with dark navy navigation and teal/amber/red status accents. It must include after-market stock recommendations, next-day price plans, historical backtest charts, abnormal news-event analysis, sector fund-flow heatmap, and fixed strategy settings. Avoid marketing hero sections, stock photos, huge gradients, and unconditional buy language. Use Chinese labels and show risk boundaries everywhere.
```
