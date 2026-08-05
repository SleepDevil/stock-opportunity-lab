export type StockBoardCode = 'main' | 'startup' | 'star' | 'bse' | 'unknown';

export type TrendPoint = {
  日期: string;
  开盘?: number | null;
  收盘?: number | null;
  最高?: number | null;
  最低?: number | null;
  成交量?: number | null;
  成交额?: number | null;
};

export type IntradayPoint = {
  时间: string;
  股票代码: string;
  开盘?: number | null;
  收盘?: number | null;
  最高?: number | null;
  最低?: number | null;
  成交量?: number | null;
  成交额?: number | null;
  均价?: number | null;
};

export type IntradayResponse = {
  symbol: string;
  period: string;
  trade_date?: string | null;
  source: string;
  message?: string | null;
  previous_close?: number | null;
  total_market_cap?: number | null;
  float_market_cap?: number | null;
  rows: IntradayPoint[];
};

export type IntradayAlert = {
  id: string;
  code: string;
  name: string;
  signal: string;
  level: string;
  tone: string;
  title: string;
  detail: string;
  triggered_at?: string | null;
  latest_price?: number | null;
  reference_price?: number | null;
  pct_from_reference?: number | null;
  plan_low?: number | null;
  plan_high?: number | null;
  stop_price?: number | null;
  breakout_price?: number | null;
};

export type IntradayAlertsResponse = {
  screen_date: string;
  trade_date: string;
  monitor_scope: 'candidates' | 'targets';
  generated_at: string;
  candidate_count: number;
  alert_count: number;
  alerts: IntradayAlert[];
};

export type WechatSubscription = {
  id: string;
  source_name: string;
  sample_url?: string | null;
  feed_url?: string | null;
  capability: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type WechatMentionedStock = {
  code: string;
  name: string;
  reason: string;
  evidence: string;
  confidence: number;
};

export type WechatKnowledge = {
  summary: string;
  tags: string[];
  opportunities: string[];
  risks: string[];
  market_relevance: 'low' | 'medium' | 'high' | string;
  source_name: string;
  stocks?: WechatMentionedStock[];
};

export type WechatArticle = {
  id: string;
  subscription_id: string;
  source_name: string;
  title: string;
  url: string;
  publish_time?: string | null;
  content_text: string;
  knowledge: WechatKnowledge;
  created_at: string;
  updated_at: string;
};

export type WechatKnowledgeResponse = {
  subscriptions: WechatSubscription[];
  articles: WechatArticle[];
  capability_note: string;
  gateway?: {
    configured?: boolean;
    kind?: string;
    label?: string;
    base_url?: string;
  };
};

export type WechatSubscriptionRequest = {
  source_name?: string | null;
  sample_url?: string | null;
  feed_url?: string | null;
};

export type WechatArticleIngestRequest = {
  source_name?: string | null;
  article_url: string;
  feed_url?: string | null;
  html?: string | null;
};

export type WechatKnowledgeQuery = {
  from_date?: string | null;
  to_date?: string | null;
  limit?: number | null;
};

export type WechatKnowledgeSyncRequest = WechatKnowledgeQuery;

export type WechatKnowledgeSyncResponse = {
  subscription_count: number;
  synced_count: number;
  articles: WechatArticle[];
  errors: Array<{ source_name: string; message: string }>;
};

export type ScreenReportsResponse = {
  dates: string[];
  latest?: string | null;
};

export type SectorScope = 'candidates' | 'targets';

export type SectorAggregateRow = {
  name: string;
  count: number;
  amount: number;
  amount_share: number;
  avg_score: number;
  avg_pct_change: number;
  avg_turnover: number;
  avg_volume_ratio: number;
  avg_float_market_cap: number;
  top_names: string[];
};

export type RealtimeSectorFundFlowRow = {
  rank: number;
  name: string;
  pct_change: number;
  main_net_inflow: number;
  main_net_inflow_ratio: number;
  super_large_net_inflow: number;
  large_net_inflow: number;
  medium_net_inflow: number;
  small_net_inflow: number;
  leader_stock?: string | null;
  leader_stock_code?: string | null;
};

export type RealtimeSectorFundFlow = {
  trade_date: string;
  source: string;
  status: 'live' | 'unavailable' | 'disabled';
  error?: string | null;
  industry_total_net_inflow: number;
  concept_total_net_inflow: number;
  industry_inflow_count: number;
  industry_outflow_count: number;
  industry_rows: RealtimeSectorFundFlowRow[];
  concept_rows: RealtimeSectorFundFlowRow[];
};

export type SectorStockRow = {
  code: string;
  name: string;
  board: string;
  industry?: string | null;
  tag?: string | null;
  amount: number;
  score: number;
  pct_change: number;
  turnover: number;
  volume_ratio: number;
};

export type CrisisIndicator = {
  key: string;
  title: string;
  value?: number | null;
  unit: string;
  date?: string | null;
  status: string;
  tone: string;
  score: number;
  summary: string;
  detail: string;
  source: string;
  precision: string;
  components: Array<{
    label: string;
    value?: number | string | null;
    unit?: string;
  }>;
};

export type CrisisMonitorResponse = {
  trade_date: string;
  generated_at: string;
  risk_score: number;
  risk_level: string;
  risk_label: string;
  summary: string;
  indicators: CrisisIndicator[];
  notes: string[];
};

export type SectorFlowResponse = {
  trade_date: string;
  scope: SectorScope;
  source_count: number;
  total_amount: number;
  avg_score: number;
  avg_pct_change: number;
  avg_turnover: number;
  avg_volume_ratio: number;
  leader?: string | null;
  board_rows: SectorAggregateRow[];
  industry_rows: SectorAggregateRow[];
  tag_rows: SectorAggregateRow[];
  top_candidates: SectorStockRow[];
  realtime_fund_flow?: RealtimeSectorFundFlow | null;
  crisis_monitor?: CrisisMonitorResponse | null;
};

export type SectorConstituentType = 'industry' | 'concept';
export type SectorLookupType = SectorConstituentType | 'auto';

export type SectorConstituentRow = {
  code: string;
  name: string;
  price: number;
  pct_change: number;
  change: number;
  amount: number;
  volume: number;
  turnover: number;
  amplitude: number;
};

export type SectorConstituentsResponse = {
  sector_type: SectorConstituentType;
  name: string;
  stock_count: number;
  source: string;
  stocks: SectorConstituentRow[];
};

export type SectorLookupResponse = SectorConstituentsResponse & {
  query: string;
  trade_date: string;
  fund_flow: RealtimeSectorFundFlowRow;
};

export type ThemeMatch = {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  match_source: 'custom' | 'eastmoney_concept' | 'unmatched';
  matched_keyword: string;
};

export type ThemeFlowSummary = {
  stock_count: number;
  matched_count: number;
  total_amount: number;
  weighted_pct_change: number;
  total_main_net_inflow: number;
  up_count: number;
  down_count: number;
};

export type ThemeFlowStock = {
  code: string;
  name: string;
  reason: string;
  latest_price: number;
  pct_change: number;
  amount: number;
  turnover: number;
  main_net_inflow: number;
  fund_inflow: number;
  fund_outflow: number;
  matched: boolean;
};

export type ThemeTrendPoint = {
  date: string;
  index: number;
  weighted_pct_change: number;
  amount: number;
};

export type ThemeFlowResponse = {
  query: string;
  trade_date: string;
  theme: ThemeMatch;
  summary: ThemeFlowSummary;
  stocks: ThemeFlowStock[];
  trend: ThemeTrendPoint[];
  fund_status: 'live' | 'unavailable' | 'disabled';
  price_source: string;
  notes: string[];
};

export type NewsThemeStock = {
  code: string;
  name: string;
  reason: string;
  confidence: number;
};

export type NewsThemeEvidence = {
  source_id: string;
  title: string;
  snippet: string;
  url: string;
  source: string;
  published_at: string;
};

export type NewsThemeCandidate = {
  id: string;
  name: string;
  aliases: string[];
  industry_chain: string[];
  catalyst: string;
  risk: string;
  confidence: number;
  stocks: NewsThemeStock[];
  source_ids: string[];
  evidence: NewsThemeEvidence[];
};

export type NewsSourceItem = {
  id: string;
  title: string;
  content: string;
  source: string;
  published_at: string;
  url: string;
  kind: string;
  keyword: string;
};

export type NewsThemeScanRequest = {
  date?: string | null;
  refresh?: boolean;
  keywords?: string[];
};

export type NewsThemeScanResponse = {
  status: 'completed';
  run_id: string;
  trade_date: string;
  generated_at: string;
  source_count: number;
  themes: NewsThemeCandidate[];
  source_items: NewsSourceItem[];
  notes: string[];
  disclaimer: string;
};

export type Candidate = {
  排名: number;
  代码: string;
  名称: string;
  交易板块?: string;
  交易板块代码?: StockBoardCode | string;
  最新价: number;
  涨跌幅: number;
  成交额: number;
  换手率: number;
  量比: number;
  总市值: number;
  流通市值: number;
  '60日涨跌幅': number;
  score: number;
  学习样本数?: number | null;
  '学习胜率%'?: number | null;
  '学习平均收益%'?: number | null;
  学习动作?: string | null;
  学习提示?: string | null;
  机会标签: string;
  计划低吸价: number;
  计划买入上限: number;
  突破确认价: number;
  高开放弃价: number;
  止损参考价: number;
  第一止盈价: number;
  '单票仓位上限%': number;
  '单笔风险预算%': number;
  行业?: string;
  上市时间?: string;
  买入策略: string;
  走势点位?: TrendPoint[] | string | null;
};

export type BacktestRow = Candidate & {
  实际日期?: string;
  实际开盘?: number;
  实际最高?: number;
  实际最低?: number;
  实际收盘?: number;
  实际涨跌幅?: number;
  实际成交额?: number;
  实际换手率?: number;
  是否买入: boolean;
  买入方式: string;
  模拟买入价?: number | null;
  '收盘浮盈%'?: number | null;
  '盘中最大浮盈%'?: number | null;
  '盘中最大回撤%'?: number | null;
  盘中触及止损?: boolean | null;
  盘中触及止盈?: boolean | null;
  收盘站上计划上限?: boolean | null;
};

export type LearningReasonCount = {
  reason: string;
  count: number;
};

export type LearningUserNote = {
  author: string;
  note: string;
  created_at: string;
};

export type LearningRecord = {
  id: string;
  screen_date: string;
  actual_date: string;
  code: string;
  name: string;
  rank?: number | null;
  entry_triggered: boolean;
  entry_mode: string;
  outcome: 'win' | 'loss' | 'missed' | 'flat' | 'unknown' | string;
  close_return_pct?: number | null;
  max_drawdown_pct?: number | null;
  max_profit_pct?: number | null;
  touched_stop_loss?: boolean | null;
  touched_take_profit?: boolean | null;
  closed_above_plan_high?: boolean | null;
  system_reasons: string[];
  system_attribution: string;
  features: Record<string, unknown>;
  user_notes: LearningUserNote[];
  created_at: string;
  updated_at: string;
};

export type LearningStrategyInsights = {
  target_win_rate: number;
  win_rate_gap: number;
  sample_status: string;
  recommendations: string[];
};

export type LearningSummary = {
  total_cases: number;
  buy_cases: number;
  winning_buys: number;
  losing_buys: number;
  missed_cases: number;
  buy_win_rate: number;
  avg_buy_return: number;
  avg_max_drawdown: number;
  user_feedback_count: number;
  top_failure_reasons: LearningReasonCount[];
  top_success_reasons: LearningReasonCount[];
  strategy_insights: LearningStrategyInsights;
  recent_records: LearningRecord[];
  updated_at?: string | null;
};

export type LearningFeedbackRequest = {
  screen_date: string;
  actual_date: string;
  code: string;
  note: string;
  author?: string | null;
};

export type LearningFeedbackResponse = {
  record: LearningRecord;
  summary: LearningSummary;
};

export type StrategyParameterChange = {
  parameter: string;
  current: number;
  proposed: number;
  direction: 'up' | 'down' | string;
  reason: string;
  confidence: 'low' | 'medium' | 'high' | string;
};

export type StrategyExperimentPlan = {
  name: string;
  status: string;
  metric: string;
  notes: string;
};

export type StrategyExperimentOutcome = {
  id: string;
  experiment_id: string;
  variant: 'baseline' | 'proposed' | string;
  screen_date: string;
  actual_date: string;
  candidate_count: number;
  bought_count: number;
  buy_win_rate: number;
  avg_close_return: number;
  avg_max_drawdown: number;
  summary: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type StrategyExperiment = {
  id: string;
  status: string;
  target_win_rate: number;
  current_metrics: Record<string, unknown>;
  current_strategy: Record<string, number>;
  proposed_strategy: Record<string, number>;
  parameter_changes: StrategyParameterChange[];
  experiment_plan: StrategyExperimentPlan[];
  disclaimer: string;
  created_at: string;
  updated_at: string;
  outcomes: StrategyExperimentOutcome[];
};

export type StrategyOptimizationResponse = {
  target_win_rate: number;
  current_metrics: Record<string, unknown>;
  current_strategy: Record<string, number>;
  proposed_strategy: Record<string, number>;
  parameter_changes: StrategyParameterChange[];
  experiment_plan: StrategyExperimentPlan[];
  experiment: StrategyExperiment;
  experiment_history: StrategyExperiment[];
  disclaimer: string;
};

export type ScreenResponse = {
  status: 'completed';
  trade_date: string;
  raw_count: number;
  filtered_count: number;
  target_count?: number;
  board_excluded_count?: number;
  excluded_boards?: string[];
  candidates: Candidate[];
  report_paths: Record<string, string>;
  ai_payload: unknown;
  analysis: string;
};

export type TaskAcceptedResponse = {
  status: 'queued' | 'running' | 'completed' | 'failed';
  task_id: string;
  kind: string;
  trade_date: string;
  message: string;
  notification_email?: string | null;
  progress?: number;
  progress_label?: string | null;
};

export type TaskProgressEvent = {
  timestamp: string;
  progress: number;
  message: string;
  elapsed_seconds?: number | null;
};

export type TaskStatusResponse = TaskAcceptedResponse & {
  created_at: string;
  updated_at: string;
  result?: ScreenResponse | QuantBacktestResponse | Record<string, unknown> | null;
  error?: string | null;
  logs?: TaskProgressEvent[];
};

export type ScreenResult = ScreenResponse | TaskAcceptedResponse;

export type BacktestResponse = {
  screen_date: string;
  actual_date: string;
  rows: BacktestRow[];
  summary: {
    candidate_count: number;
    bought_count: number;
    no_entry_count: number;
    entry_rate: number;
    win_rate: number;
    avg_close_return: number;
    median_close_return: number;
    avg_max_drawdown: number;
    best?: { code: string; name: string; return: number; entry_mode: string } | null;
    worst?: { code: string; name: string; return: number; entry_mode: string } | null;
  };
  learning_summary: LearningSummary;
  report_paths: Record<string, string>;
  ai_payload: unknown;
  analysis: string;
};

export type RecommendationCurvePoint = {
  date: string;
  close?: number | null;
  return_pct?: number | null;
  daily_return_pct?: number | null;
  benchmark_return_pct?: number | null;
  excess_return_pct?: number | null;
  price_carried_forward?: boolean;
};

export type RecommendationPerformanceStock = {
  code: string;
  name: string;
  rank?: number | null;
  score?: number | null;
  report_date: string;
  entry_date?: string | null;
  recommendation_price?: number | null;
  plan_low?: number | null;
  plan_high?: number | null;
  avoid_gap_price?: number | null;
  opportunity_tag?: string | null;
  status: 'tracked' | 'pending_entry' | 'no_entry_price';
  status_label: string;
  entry_price?: number | null;
  latest_price?: number | null;
  valuation_date?: string | null;
  latest_stock_price_date?: string | null;
  return_pct?: number | null;
  benchmark_return_pct?: number | null;
  excess_return_pct?: number | null;
  plan_status?: 'within_plan' | 'above_plan' | 'above_abandon' | 'below_plan' | 'unknown' | null;
  plan_status_label: string;
  curve: RecommendationCurvePoint[];
};

export type RecommendationPerformanceCohort = {
  report_date: string;
  entry_date?: string | null;
  valuation_date?: string | null;
  status: 'tracked' | 'empty' | 'pending_entry' | 'no_price';
  message: string;
  candidate_count: number;
  tracked_count: number;
  current_return_pct?: number | null;
  benchmark_return_pct?: number | null;
  excess_return_pct?: number | null;
  win_rate_pct?: number | null;
  curve: RecommendationCurvePoint[];
  stocks: RecommendationPerformanceStock[];
};

export type RecommendationPerformanceCalendarDay = {
  date: string;
  weekday: string;
  status: 'reported' | 'reported_empty' | 'missing_report' | 'market_closed';
  status_label: string;
  candidate_count: number;
  tracked_count: number;
  return_pct?: number | null;
};

export type RecommendationPerformanceResponse = {
  status: 'completed';
  requested_as_of_date: string;
  as_of_date: string;
  period_start: string;
  period_end: string;
  lookback_days: number;
  benchmark: { code: string; name: string };
  entry_assumption: {
    label: string;
    price_field: string;
    position_method: string;
    costs_included: boolean;
    exit_rule: string;
    notes: string[];
  };
  summary: {
    trading_day_count: number;
    report_day_count: number;
    missing_report_day_count: number;
    missing_report_dates: string[];
    report_coverage_pct?: number | null;
    recommendation_count: number;
    tracked_count: number;
    tracked_cohort_count: number;
    win_rate_pct?: number | null;
    average_return_pct?: number | null;
    average_excess_return_pct?: number | null;
    cohort_average_return_pct?: number | null;
    best?: { code: string; name: string; report_date: string; return_pct: number } | null;
    worst?: { code: string; name: string; report_date: string; return_pct: number } | null;
  };
  calendar_days: RecommendationPerformanceCalendarDay[];
  cohorts: RecommendationPerformanceCohort[];
  data_quality: {
    valuation_basis: string;
    is_intraday: boolean;
    latest_market_date?: string | null;
    failed_symbols: string[];
    notes: string[];
  };
  disclaimer: string;
};

export type QuantEngine = 'auto' | 'internal' | 'vectorbt';
export type QuantStockPool = 'manual' | 'screen_candidates' | 'screen_targets';
export type QuantStrategy = 'opportunity_pool' | 'ma_trend' | 'volume_breakout' | 'rsi_reversion' | 'momentum_rank';

export type QuantBacktestRequest = {
  engine?: QuantEngine;
  stock_pool?: QuantStockPool;
  symbols?: string[];
  screen_date?: string | null;
  start_date: string;
  end_date: string;
  strategy?: QuantStrategy;
  refresh?: boolean;
  fee_rate?: number;
  slippage_rate?: number;
  sell_stamp_tax_rate?: number;
  max_positions?: number;
  position_pct?: number;
  parameters?: Record<string, unknown>;
  parameter_grid?: Record<string, number[]>;
};

export type QuantStrategyParameter = {
  key: string;
  label: string;
  type: 'integer' | 'number' | 'percent' | 'money' | string;
  default?: number | string | null;
  min?: number;
  max?: number;
  step?: number;
};

export type QuantStrategyTemplate = {
  id: QuantStrategy | string;
  name: string;
  description: string;
  parameters: QuantStrategyParameter[];
};

export type QuantEngineTemplate = {
  id: QuantEngine | string;
  name: string;
  description: string;
};

export type QuantStrategyCatalogResponse = {
  strategies: QuantStrategyTemplate[];
  engines: QuantEngineTemplate[];
  engine_status?: {
    available?: boolean;
    message?: string;
    version?: string | null;
    [key: string]: unknown;
  };
};

export type QuantEquityPoint = {
  date: string;
  equity: number;
  daily_return_pct: number;
  holding_count: number;
};

export type QuantDrawdownPoint = {
  date: string;
  drawdown_pct: number;
};

export type QuantBenchmarkPoint = {
  date: string;
  label: string;
  close: number;
  daily_return_pct: number;
  return_pct: number;
};

export type QuantTrade = {
  symbol: string;
  name?: string | null;
  display?: string | null;
  entry_date: string;
  exit_date: string;
  entry_price?: number | null;
  exit_price?: number | null;
  quantity?: number | null;
  return_pct?: number | null;
  exit_reason: string;
};

export type QuantBuyOrder = {
  symbol: string;
  name?: string | null;
  display?: string | null;
  price?: number | null;
  quantity?: number | null;
  price_type?: string | null;
  notional?: number | null;
  reason: string;
};

export type QuantSellOrder = {
  symbol: string;
  name?: string | null;
  display?: string | null;
  price?: number | null;
  quantity?: number | null;
  price_type?: string | null;
  notional?: number | null;
  reason: string;
  entry_date?: string | null;
  entry_price?: number | null;
  return_pct?: number | null;
};

export type QuantPosition = {
  date: string;
  symbol: string;
  name?: string | null;
  display?: string | null;
  entry_date: string;
  entry_price: number;
  quantity?: number | null;
  close?: number | null;
  return_pct?: number | null;
};

export type QuantHoldingPosition = {
  symbol: string;
  name?: string | null;
  display?: string | null;
};

export type QuantDailyAction = {
  date: string;
  equity: number;
  strategy_daily_return_pct?: number | null;
  strategy_return_pct?: number | null;
  benchmark_daily_return_pct?: number | null;
  benchmark_return_pct?: number | null;
  buy_symbols: string[];
  sell_symbols: string[];
  buy_orders: QuantBuyOrder[];
  sell_orders: QuantSellOrder[];
  holding_symbols: string[];
  holding_positions?: QuantHoldingPosition[];
  holding_count: number;
  observation_reason: string;
  notes: string[];
};

export type QuantParameterRanking = {
  rank: number;
  strategy: string;
  parameters: Record<string, unknown>;
  total_return_pct: number;
  max_drawdown_pct: number;
  trade_count: number;
  win_rate: number;
  unfilled_reason_count?: number;
  t1_blocked_count?: number;
  price_missing_count?: number;
  lot_blocked_count?: number;
  capacity_blocked_count?: number;
};

export type QuantBacktestResponse = {
  status: 'completed';
  run_id: string;
  engine: 'internal' | 'vectorbt';
  engine_status: {
    requested_engine?: string;
    selected_engine?: string;
    vectorbt_available?: boolean;
    fallback?: boolean;
    message?: string;
    version?: string | null;
    [key: string]: unknown;
  };
  strategy: string;
  stock_pool: string;
  start_date: string;
  end_date: string;
  screen_date?: string | null;
  symbols: string[];
  summary: {
    initial_equity: number;
    ending_equity: number;
    total_return_pct: number;
    max_drawdown_pct: number;
    trade_count: number;
    win_rate: number;
    avg_trade_return_pct: number;
    symbol_count: number;
    parameters: Record<string, unknown>;
  };
  equity_curve: QuantEquityPoint[];
  drawdown_curve: QuantDrawdownPoint[];
  benchmark_curve: QuantBenchmarkPoint[];
  trades: QuantTrade[];
  positions: QuantPosition[];
  daily_actions: QuantDailyAction[];
  parameter_rankings: QuantParameterRanking[];
  report_paths: Record<string, string>;
  disclaimer: string;
};

export type QuantRunSummary = Pick<
  QuantBacktestResponse,
  'run_id' | 'engine' | 'strategy' | 'stock_pool' | 'start_date' | 'end_date' | 'screen_date' | 'symbols' | 'summary' | 'report_paths'
> & {
  generated_at?: string | null;
};

export type QuantRunsResponse = {
  runs: QuantRunSummary[];
};

export type EvolutionCycleRequest = {
  actual_date?: string | null;
  screen_date?: string | null;
  refresh?: boolean;
  exclude_boards?: string[];
};

export type EvolutionCycleResponse = {
  status: 'completed';
  screen_date: string;
  actual_date: string;
  backtest: BacktestResponse;
  learning_summary: LearningSummary;
  strategy_optimization: StrategyOptimizationResponse;
  message: string;
};

export type StockAnalysisResponse = {
  query: string;
  trade_date: string;
  code: string;
  name: string;
  board?: string | null;
  board_code?: string | null;
  latest: {
    price?: number | null;
    pct_change?: number | null;
    amount?: number | null;
    turnover?: number | null;
    volume_ratio?: number | null;
    float_market_cap?: number | null;
    total_market_cap?: number | null;
  };
  plan: {
    计划低吸价?: number | null;
    计划买入上限?: number | null;
    突破确认价?: number | null;
    高开放弃价?: number | null;
    止损参考价?: number | null;
    第一止盈价?: number | null;
    '单票仓位上限%'?: number | null;
    '单笔风险预算%'?: number | null;
    买入策略?: string | null;
  };
  position?: {
    quantity: number;
    cost_price: number;
    market_value: number;
    cost_value: number;
    floating_pnl: number;
    floating_pnl_pct: number;
  } | null;
  trend: {
    days: number;
    pct_5?: number | null;
    pct_20?: number | null;
    pct_60?: number | null;
    ma_5?: number | null;
    ma_20?: number | null;
    drawdown_from_60d_high?: number | null;
    position_in_60d_range?: number | null;
  };
  trend_points: TrendPoint[];
  recommendation: {
    action: string;
    tone: string;
    title: string;
    summary: string;
    bullets: string[];
  };
  disclaimer: string;
};

export type StockKlineResponse = {
  query: string;
  trade_date: string;
  code: string;
  name: string;
  source: string;
  latest?: StockSearchItem | Record<string, unknown> | null;
  total_market_cap?: number | null;
  float_market_cap?: number | null;
  trend_points: TrendPoint[];
};

export type FinancialStatementRow = {
  report_date: string;
  announcement_date?: string | null;
  revenue?: number | null;
  net_profit?: number | null;
  operating_profit?: number | null;
  eps?: number | null;
  operating_cash_flow?: number | null;
  total_assets?: number | null;
  total_liabilities?: number | null;
  asset_liability_ratio?: number | null;
  gross_margin?: number | null;
  roe?: number | null;
  revenue_growth?: number | null;
  net_profit_growth?: number | null;
  audit_status?: string | null;
};

export type FinancialIndicatorRow = {
  report_date: string;
  gross_margin?: number | null;
  roe?: number | null;
  asset_liability_ratio?: number | null;
  revenue_growth?: number | null;
  net_profit_growth?: number | null;
  current_ratio?: number | null;
  quick_ratio?: number | null;
};

export type DisclosureReport = {
  code: string;
  name: string;
  title: string;
  publish_date?: string | null;
  url: string;
};

export type StockFinancialsResponse = {
  code: string;
  years: number;
  source: string;
  summary: {
    latest_report_date?: string | null;
    latest_revenue?: number | null;
    latest_net_profit?: number | null;
    latest_operating_cash_flow?: number | null;
    latest_roe?: number | null;
    latest_asset_liability_ratio?: number | null;
    latest_revenue_growth?: number | null;
    latest_net_profit_growth?: number | null;
    tone?: string | null;
    bullets: string[];
  };
  statements: FinancialStatementRow[];
  indicators: FinancialIndicatorRow[];
  disclosures: DisclosureReport[];
  disclaimer: string;
};

export type StockNoticeItem = {
  code: string;
  name: string;
  title: string;
  category: string;
  publish_date?: string | null;
  source: string;
  url: string;
};

export type StockNewsItem = {
  keyword: string;
  title: string;
  content: string;
  publish_time: string;
  source: string;
  url: string;
};

export type DragonTigerSeat = {
  rank?: number | null;
  branch: string;
  buy_amount?: number | null;
  buy_ratio?: number | null;
  sell_amount?: number | null;
  sell_ratio?: number | null;
  net_amount?: number | null;
  type: string;
};

export type DragonTigerSummary = {
  trade_date?: string | null;
  interpretation?: string | null;
  close_price?: number | null;
  pct_change?: number | null;
  net_buy_amount?: number | null;
  buy_amount?: number | null;
  sell_amount?: number | null;
  dragon_tiger_amount?: number | null;
  market_total_amount?: number | null;
  turnover?: number | null;
  float_market_cap?: number | null;
  reason?: string | null;
};

export type DragonTigerInstitution = {
  trade_date?: string | null;
  buy_count?: number | null;
  sell_count?: number | null;
  buy_amount?: number | null;
  sell_amount?: number | null;
  net_amount?: number | null;
};

export type StockIntelligenceResponse = {
  code: string;
  trade_date: string;
  query_start_date?: string | null;
  query_end_date?: string | null;
  notice_start_date: string;
  notice_end_date: string;
  source: string;
  notices: StockNoticeItem[];
  news: StockNewsItem[];
  dragon_tiger: {
    available_dates: string[];
    summary?: DragonTigerSummary | null;
    institution?: DragonTigerInstitution | null;
    buy_seats: DragonTigerSeat[];
    sell_seats: DragonTigerSeat[];
  };
  disclaimer: string;
};

export type StockSearchItem = {
  code: string;
  name: string;
  board?: string | null;
  board_code?: string | null;
  initials: string;
  pinyin?: string;
  latest_price?: number | null;
  pct_change?: number | null;
};

export type StockSearchResponse = {
  query: string;
  trade_date: string;
  results: StockSearchItem[];
};

export type StockQuote = {
  code: string;
  name: string;
  price?: number | null;
  pct_change?: number | null;
  change?: number | null;
  volume?: number | null;
  amount?: number | null;
  turnover?: number | null;
  high?: number | null;
  low?: number | null;
  open?: number | null;
  previous_close?: number | null;
  total_market_cap?: number | null;
  float_market_cap?: number | null;
  updated_at?: string | null;
};

export type StockQuotesResponse = {
  trade_date: string;
  updated_at: string;
  source: string;
  is_stale: boolean;
  message?: string | null;
  quotes: StockQuote[];
};

export type StockIntradayPoint = {
  time: string;
  price: number;
  average?: number | null;
};

export type StockIntradaySparkline = {
  code: string;
  trade_date?: string | null;
  previous_close?: number | null;
  points: StockIntradayPoint[];
};

export type StockIntradaySparklinesResponse = {
  trade_date: string;
  updated_at: string;
  source: string;
  is_stale: boolean;
  message?: string | null;
  sparklines: StockIntradaySparkline[];
};

export type MarketIndexPoint = StockIntradayPoint & {
  amount?: number | null;
};

export type MarketIndexResponse = {
  code: string;
  name: string;
  trade_date?: string | null;
  updated_at: string;
  source: string;
  is_stale: boolean;
  message?: string | null;
  price?: number | null;
  pct_change?: number | null;
  change?: number | null;
  amount?: number | null;
  high?: number | null;
  low?: number | null;
  open?: number | null;
  previous_close?: number | null;
  points: MarketIndexPoint[];
};

export type WatchlistCommentaryQuote = {
  code: string;
  name: string;
  price?: number | null;
  pct_change?: number | null;
  change?: number | null;
  amount?: number | null;
  turnover?: number | null;
  high?: number | null;
  low?: number | null;
  open?: number | null;
  previous_close?: number | null;
  updated_at?: string | null;
};

export type WatchlistCommentaryRequest = {
  slot: string;
  captured_at: string;
  user_email?: string | null;
  session: 'preopen' | 'trading' | 'break' | 'closed';
  manual?: boolean;
  is_stale?: boolean;
  quotes: WatchlistCommentaryQuote[];
  market?: {
    code: string;
    name: string;
    price?: number | null;
    pct_change?: number | null;
    change?: number | null;
    amount?: number | null;
    updated_at?: string | null;
  } | null;
};

export type WatchlistCommentaryMover = {
  code: string;
  name: string;
  pct_change: number;
};

export type WatchlistCommentaryResponse = {
  trade_date: string;
  slot: string;
  trigger: 'scheduled' | 'manual';
  generated_at: string;
  source_updated_at?: string | null;
  mode: 'external_ai' | 'rules_fallback';
  provider: 'zhipu' | 'external_command' | 'rules_fallback';
  model?: string | null;
  title: string;
  commentary: string;
  stocks: Array<{
    code: string;
    name: string;
    price?: number | null;
    pct_change?: number | null;
  }>;
  summary: {
    total: number;
    measured: number;
    rising: number;
    falling: number;
    flat: number;
    average_pct?: number | null;
    leader?: WatchlistCommentaryMover | null;
    laggard?: WatchlistCommentaryMover | null;
  };
  note?: string | null;
  disclaimer: string;
  delivery: {
    status: 'sent' | 'disabled' | 'unconfigured' | 'outside_session' | 'failed';
    message: string;
  };
};

export type AppConfig = {
  data_dir: string;
  screen: Record<string, unknown>;
  strategy: Record<string, unknown>;
  ai?: {
    configured: boolean;
    provider: 'zhipu' | 'external_command' | 'rules_fallback';
    requested_provider: 'auto' | 'zhipu' | 'command' | 'rules';
    model?: string | null;
  };
};

export type NotificationSettings = {
  user_email?: string | null;
  board_exclusion_enabled?: boolean;
  excluded_boards?: string[];
  watchlist_commentary_feishu_enabled?: boolean | null;
  watchlist_commentary_feishu_chat_id?: string | null;
  watchlist_commentary_platform_url?: string | null;
};

export type ServerWatchlist = {
  user_email: string;
  stocks: Array<{
    code: string;
    name: string;
  }>;
  source: 'stored' | 'deployment_default' | 'empty';
  updated_at?: string | null;
};
