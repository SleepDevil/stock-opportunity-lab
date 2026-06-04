# Stitch Visual Review - 2026-06-03

## Context

The user reviewed the first Google Stitch output and found it too ordinary: visually close to a traditional backend/admin dashboard rather than a polished stock research product. The Stitch project was inspected in Chrome and refined through two prompts:

- `docs/prompts/google-stitch-redesign-v2.md`
- `docs/prompts/google-stitch-polish-v3.md`

## Original Issues

- The first version looked like a generic admin system: left sidebar, KPI cards, table, right cards.
- Several module names were in English, which broke the Chinese A-share product tone.
- Dark-dashboard styling created a generic fintech/control-room feel instead of a precise personal research terminal.
- The candidate list was too table-first; it did not communicate why each stock deserved attention.

## V3 Improvements

- Most user-facing screen titles are now Chinese:
  - 今日机会 - 量化投研工作站
  - 投研卡片 - 华宏科技 002645
  - 策略实验室 - 固定策略 V1
  - 消息异动 - 事件调查台
  - 板块资金地图与情绪看板
  - 策略逻辑蓝图 - 规则配置
- The visual tone is calmer and more professional: cold white workspace, deep ink navigation, compact numeric rhythm.
- The product concepts are stronger: 市场状态带、机会中枢、今日决策栈、事件调查台、板块资金地图.
- It has moved away from a marketing page and closer to a usable desktop research tool.

## Remaining Problems

- The dashboard still reads as a refined table layout, not a truly distinctive opportunity workflow.
- The right rail still risks feeling like stacked admin cards unless each item is interactive and evidence-driven.
- The current screenshot uses repeated row patterns; the implementation should introduce clearer hierarchy between top-ranked and lower-confidence candidates.
- Some generated microcopy may still be too small or too dense; final code needs real responsive and accessibility checks.

## Implementation Direction

Use Stitch V3 as visual reference, not as a source to copy directly.

Build the real UI around these surfaces:

1. Market state ribbon:
   - Trading date, market mood, breadth, turnover, data freshness, cache state.

2. Opportunity strips:
   - Each candidate is a horizontal research strip, not a conventional table row.
   - Required content: rank badge, score, stock name/code, sector tags, strategy trigger, mini K-line, entry range, buy trigger, stop reference, target/reference exit, evidence status.

3. Decision stack:
   - Right-side panel should answer: why now, what confirms, what invalidates, what to inspect next.
   - Items should deep-link to news, sector, and backtest evidence.

4. Detail page:
   - Preserve the darker analytical tone only where dense chart reading benefits from it.
   - Combine thesis, evidence timeline, price plan, sector relation, and historical analog samples.

5. Strategy lab:
   - Prioritize curve, drawdown, trade distribution, regime split, and failure cases over decorative metrics.

## Final Design Judgment

V3 is directionally usable and substantially better than the first output. It solves the biggest tone problems, but it should not be treated as final UI. The coded product should keep the terminal-like precision while replacing the remaining admin-table skeleton with opportunity strips and evidence-first interactions.
