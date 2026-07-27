import type {
  AppConfig,
  LearningSummary,
  NotificationSettings,
  QuantRunsResponse,
  QuantStrategyCatalogResponse,
  ScreenReportsResponse,
  StrategyExperiment,
  StrategyOptimizationResponse,
  WechatKnowledgeResponse
} from '../types/api';

const unavailableMessage =
  '当前是静态镜像：页面不会连接后端、数据库或行情采集。完整扫描、写入和通知需要自行部署后端服务。';

const screenConfig = {
  // 最多展示多少只候选股。
  max_candidates: 30,
  // 股价过滤区间，排除过低风险票和过高价格票。
  min_price: 3,
  max_price: 300,
  // 当日成交额下限，默认 2 亿元，用来保证基础流动性。
  min_amount: 200_000_000,
  // 换手率区间：太低表示资金参与不足，太高可能已过热。
  min_turnover: 3,
  max_turnover: 15,
  // 量比下限：当前成交量相对近期均量的放大倍数。
  min_volume_ratio: 1.2,
  // 流通市值是实际可交易盘子，短线资金更看重这个口径。
  min_float_market_cap: 3_000_000_000,
  max_float_market_cap: 50_000_000_000,
  // 总市值是公司整体体量；min_total_market_cap 表示总市值至少 50 亿元。
  min_total_market_cap: 5_000_000_000,
  max_total_market_cap: 100_000_000_000,
  // 当日涨跌幅区间，避免太弱或接近涨停后的追高样本。
  min_pct_change: -6,
  max_pct_change: 9.5,
  // 名称过滤：排除 ST、退市整理、新股/次新首日等样本。
  exclude_name_regex: 'ST|退|N|C',
  // 各指标先按过滤后股票池做百分位排名，再按权重合成为 0-100 分。
  score_weights: {
    amount: 0.25,
    volume_ratio: 0.2,
    turnover: 0.2,
    pct_change: 0.15,
    market_cap_fit: 0.1,
    sixty_day_strength: 0.1
  }
};

const strategyConfig = {
  entry_discount: 0.012,
  entry_premium: 0.012,
  breakout_premium: 0.026,
  avoid_gap_up: 0.045,
  stop_loss: 0.055,
  take_profit: 0.085,
  max_single_position_pct: 12,
  risk_per_trade_pct: 1
};

const now = () => new Date().toISOString();

const config: AppConfig = {
  data_dir: 'static-github-pages',
  screen: {
    ...screenConfig,
    mode: 'static-mirror',
    capability_note: unavailableMessage
  },
  strategy: {
    ...strategyConfig,
    mode: 'static-mirror'
  }
};

const learningSummary: LearningSummary = {
  total_cases: 0,
  buy_cases: 0,
  winning_buys: 0,
  losing_buys: 0,
  missed_cases: 0,
  buy_win_rate: 0,
  avg_buy_return: 0,
  avg_max_drawdown: 0,
  user_feedback_count: 0,
  top_failure_reasons: [],
  top_success_reasons: [],
  strategy_insights: {
    target_win_rate: 80,
    win_rate_gap: 80,
    sample_status: 'static',
    recommendations: [unavailableMessage]
  },
  recent_records: [],
  updated_at: null
};

function staticExperiment(): StrategyExperiment {
  const createdAt = now();
  return {
    id: 'static-github-pages',
    status: 'static',
    target_win_rate: 80,
    current_metrics: {
      total_cases: 0,
      buy_cases: 0,
      buy_win_rate: 0,
      avg_buy_return: 0,
      avg_max_drawdown: 0
    },
    current_strategy: strategyConfig,
    proposed_strategy: strategyConfig,
    parameter_changes: [],
    experiment_plan: [
      {
        name: '连接完整后端后开始记录样本',
        status: 'static',
        metric: 'buy_win_rate',
        notes: unavailableMessage
      }
    ],
    disclaimer: unavailableMessage,
    created_at: createdAt,
    updated_at: createdAt,
    outcomes: []
  };
}

function strategyOptimization(): StrategyOptimizationResponse {
  const experiment = staticExperiment();
  return {
    target_win_rate: 80,
    current_metrics: experiment.current_metrics,
    current_strategy: strategyConfig,
    proposed_strategy: strategyConfig,
    parameter_changes: [],
    experiment_plan: experiment.experiment_plan,
    experiment,
    experiment_history: [],
    disclaimer: unavailableMessage
  };
}

const wechatKnowledge: WechatKnowledgeResponse = {
  subscriptions: [],
  articles: [],
  capability_note: unavailableMessage
};

const screenReports: ScreenReportsResponse = {
  dates: [],
  latest: null
};

const quantRuns: QuantRunsResponse = {
  runs: []
};

const quantStrategies: QuantStrategyCatalogResponse = {
  strategies: [
    {
      id: 'ma_trend',
      name: '均线趋势',
      description: '快线高于慢线时持有，快线跌回慢线下方退出。',
      parameters: [
        { key: 'fast_window', label: '快线周期', type: 'integer', default: 5, min: 1, max: 120, step: 1 },
        { key: 'slow_window', label: '慢线周期', type: 'integer', default: 20, min: 2, max: 240, step: 1 }
      ]
    },
    {
      id: 'volume_breakout',
      name: '放量突破',
      description: '按涨幅、成交额和量比生成突破信号。',
      parameters: [
        { key: 'pct_change_threshold', label: '涨幅阈值', type: 'percent', default: 3, min: 0, max: 20, step: 0.5 },
        { key: 'volume_ratio_threshold', label: '量比阈值', type: 'number', default: 1.5, min: 0.1, max: 10, step: 0.1 },
        { key: 'amount_threshold', label: '成交额阈值', type: 'money', default: 200_000_000, min: 0, step: 10_000_000 }
      ]
    },
    {
      id: 'rsi_reversion',
      name: 'RSI均值回归',
      description: 'RSI 跌入超卖区后买入，反弹到退出阈值卖出。',
      parameters: [
        { key: 'rsi_window', label: 'RSI周期', type: 'integer', default: 14, min: 2, max: 60, step: 1 },
        { key: 'entry_rsi', label: '入场RSI', type: 'number', default: 30, min: 5, max: 50, step: 1 },
        { key: 'exit_rsi', label: '退出RSI', type: 'number', default: 55, min: 40, max: 90, step: 1 }
      ]
    },
    {
      id: 'momentum_rank',
      name: '横截面动量排名',
      description: '按近 N 日涨幅做股票池内相对强弱排名，只买排名靠前且涨幅达标的标的。',
      parameters: [
        { key: 'lookback_window', label: '回看周期', type: 'integer', default: 20, min: 2, max: 120, step: 1 },
        { key: 'top_n', label: '买入Top N', type: 'integer', default: 10, min: 1, max: 50, step: 1 },
        { key: 'exit_rank', label: '退出排名', type: 'integer', default: 30, min: 1, max: 100, step: 1 },
        { key: 'min_return_pct', label: '最低涨幅', type: 'percent', default: 5, min: -20, max: 80, step: 1 }
      ]
    },
    {
      id: 'opportunity_pool',
      name: '当前机会池复刻',
      description: '在区间首日买入股票池、区间末日退出。',
      parameters: []
    }
  ],
  engines: [
    { id: 'vectorbt', name: 'vectorbt', description: '唯一正式量化回测引擎；通过 adapter 生成 A 股 T+1 和真实收盘成交订单。' }
  ],
  engine_status: {
    available: false,
    message: '静态镜像不会连接后端 Python 环境；本地完整模式需要 Python 3.12 .venv 并安装 vectorbt。'
  }
};

function notificationSettings(): NotificationSettings {
  return {
    user_email: null,
    board_exclusion_enabled: true,
    excluded_boards: ['startup', 'star', 'bse']
  };
}

function normalizedPath(path: string): string {
  try {
    return new URL(path, 'https://static.stock-lab.local').pathname;
  } catch {
    return path.split('?')[0] || path;
  }
}

export function isStaticMode(): boolean {
  return import.meta.env.VITE_STOCK_LAB_STATIC_MODE === 'true';
}

export async function staticRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase();
  const route = normalizedPath(path);
  if (method !== 'GET') {
    throw new Error(unavailableMessage);
  }

  const payloads: Record<string, unknown> = {
    '/api/client-auth': { csrf_token: 'static-github-pages' },
    '/api/config': config,
    '/api/learning-summary': learningSummary,
    '/api/strategy-optimization': strategyOptimization(),
    '/api/wechat-knowledge': wechatKnowledge,
    '/api/screen-reports': screenReports,
    '/api/quant/runs': quantRuns,
    '/api/quant/strategies': quantStrategies,
    '/api/notification-settings': notificationSettings()
  };

  if (route in payloads) {
    return payloads[route] as T;
  }

  throw new Error(unavailableMessage);
}
