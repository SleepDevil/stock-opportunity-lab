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
};

export type TaskStatusResponse = TaskAcceptedResponse & {
  created_at: string;
  updated_at: string;
  result?: ScreenResponse | Record<string, unknown> | null;
  error?: string | null;
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
  report_paths: Record<string, string>;
  ai_payload: unknown;
  analysis: string;
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
  latest_price?: number | null;
  pct_change?: number | null;
};

export type StockSearchResponse = {
  query: string;
  trade_date: string;
  results: StockSearchItem[];
};

export type AppConfig = {
  data_dir: string;
  screen: Record<string, unknown>;
  strategy: Record<string, unknown>;
};

export type NotificationSettings = {
  user_email?: string | null;
};
