from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import os
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_project_dotenv(project_root: Path = PROJECT_ROOT) -> None:
    project_env = project_root / ".env"
    load_dotenv(project_env, override=False)
    runtime_data_dir = os.getenv("STOCK_LAB_DATA_DIR", "").strip()
    if not runtime_data_dir:
        return
    runtime_env = Path(runtime_data_dir).expanduser() / ".env"
    if runtime_env != project_env:
        load_dotenv(runtime_env, override=False)


load_project_dotenv()
PROCESS_CLIENT_AUTH_SECRET = secrets.token_urlsafe(32)


def default_data_dir() -> Path:
    override = os.getenv("STOCK_LAB_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return PROJECT_ROOT / "data"


def default_database_url() -> str | None:
    return os.getenv("STOCK_LAB_DATABASE_URL")


def default_feishu_app_id() -> str:
    return os.getenv("STOCK_LAB_FEISHU_APP_ID", "")


def default_feishu_app_secret() -> str | None:
    return os.getenv("STOCK_LAB_FEISHU_APP_SECRET")


def default_watchlist_commentary_feishu_enabled() -> bool:
    value = os.getenv("STOCK_LAB_WATCHLIST_COMMENTARY_FEISHU_ENABLED", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def default_watchlist_commentary_feishu_chat_id() -> str | None:
    value = os.getenv("STOCK_LAB_WATCHLIST_COMMENTARY_FEISHU_CHAT_ID", "").strip()
    return value or None


def default_watchlist_commentary_platform_url() -> str | None:
    value = os.getenv("STOCK_LAB_WATCHLIST_COMMENTARY_PLATFORM_URL", "").strip()
    return value or None


def default_client_auth_secret() -> str:
    return os.getenv("STOCK_LAB_CLIENT_AUTH_SECRET") or os.getenv("STOCK_LAB_FEISHU_APP_SECRET") or PROCESS_CLIENT_AUTH_SECRET


def default_ai_provider() -> str:
    provider = os.getenv("STOCK_LAB_AI_PROVIDER", "auto").strip().lower()
    return provider if provider in {"auto", "zhipu", "command", "rules"} else "auto"


def default_ai_command() -> str | None:
    command = os.getenv("STOCK_LAB_AI_COMMAND", "").strip()
    return command or None


def default_zhipu_api_key() -> str | None:
    api_key = (
        os.getenv("STOCK_LAB_ZHIPU_API_KEY")
        or os.getenv("ZHIPUAI_API_KEY")
        or ""
    ).strip()
    return api_key or None


def default_zhipu_model() -> str:
    return os.getenv("STOCK_LAB_ZHIPU_MODEL", "glm-4.7-flash").strip() or "glm-4.7-flash"


def default_zhipu_base_url() -> str:
    return (
        os.getenv("STOCK_LAB_ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").strip()
        or "https://open.bigmodel.cn/api/paas/v4"
    )


def default_ai_timeout_seconds() -> float:
    try:
        value = float(os.getenv("STOCK_LAB_AI_TIMEOUT_SECONDS", "30"))
    except ValueError:
        return 30.0
    if not math.isfinite(value):
        return 30.0
    return min(max(value, 3.0), 120.0)


@dataclass
class ScreenConfig:
    """盘后筛选阈值。

    AkShare 返回的金额和市值字段单位是人民币“元”。这里同时看总市值和流通市值：
    total_market_cap 是总市值，约等于当前股价乘以总股本，用来排除整体体量过小或过大的公司。
    float_market_cap 是流通市值，约等于当前股价乘以可交易流通股本，更接近短线资金实际能推动的盘子。
    """

    # 最多输出多少只候选股。
    max_candidates: int = 30
    # 股价过滤区间：过低容易踩退市/壳风险，过高会让小仓位交易不友好。
    min_price: float = 3.0
    max_price: float = 300.0
    # 当日成交额下限，默认 2 亿元，保证候选有基本流动性。
    min_amount: float = 200_000_000.0
    # 换手率区间：太低说明资金参与不足，太高可能已经过热。
    min_turnover: float = 3.0
    max_turnover: float = 15.0
    # 量比下限：当前成交量相对近期均量的放大倍数。
    min_volume_ratio: float = 1.2
    # 流通市值区间：短线资金真正交易和冲击的是流通盘。
    min_float_market_cap: float = 3_000_000_000.0
    max_float_market_cap: float = 50_000_000_000.0
    # 总市值区间：公司整体体量，min_total_market_cap 表示总市值至少 50 亿元。
    min_total_market_cap: float = 5_000_000_000.0
    max_total_market_cap: float = 100_000_000_000.0
    # 当日涨跌幅区间：过滤过弱的票，也避免接近涨停的高追风险。
    min_pct_change: float = -6.0
    max_pct_change: float = 9.5
    # 名称过滤：排除 ST、退市整理、新股/次新首日等容易失真的样本。
    exclude_name_regex: str = "ST|退|N|C"
    # 排名权重：每项先在过滤后的股票池里转成百分位，再加权得到 0-100 分。
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "amount": 0.25,
            "volume_ratio": 0.20,
            "turnover": 0.20,
            "pct_change": 0.15,
            "market_cap_fit": 0.10,
            "sixty_day_strength": 0.10,
        }
    )


@dataclass
class StrategyConfig:
    # Bump this whenever execution semantics change.  The config hash is also
    # shown in the ledger so parameter-only changes remain distinguishable.
    recommendation_replay_version: str = "risk-exit-v1.0"
    entry_discount: float = 0.012
    entry_premium: float = 0.012
    breakout_premium: float = 0.026
    avoid_gap_up: float = 0.045
    stop_loss: float = 0.055
    take_profit: float = 0.085
    max_holding_days: int = 10
    commission_rate: float = 0.0003
    slippage_rate: float = 0.0005
    sell_stamp_tax_rate: float = 0.0005
    max_single_position_pct: float = 12.0
    risk_per_trade_pct: float = 1.0


@dataclass
class AppConfig:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = field(default_factory=default_data_dir)
    database_url: str | None = field(default_factory=default_database_url)
    feishu_app_id: str = field(default_factory=default_feishu_app_id)
    feishu_app_secret: str | None = field(default_factory=default_feishu_app_secret)
    watchlist_commentary_feishu_enabled: bool = field(default_factory=default_watchlist_commentary_feishu_enabled)
    watchlist_commentary_feishu_chat_id: str | None = field(default_factory=default_watchlist_commentary_feishu_chat_id)
    watchlist_commentary_platform_url: str | None = field(default_factory=default_watchlist_commentary_platform_url)
    client_auth_secret: str = field(default_factory=default_client_auth_secret)
    ai_provider: str = field(default_factory=default_ai_provider)
    ai_command: str | None = field(default_factory=default_ai_command)
    zhipu_api_key: str | None = field(default_factory=default_zhipu_api_key)
    zhipu_model: str = field(default_factory=default_zhipu_model)
    zhipu_base_url: str = field(default_factory=default_zhipu_base_url)
    ai_timeout_seconds: float = field(default_factory=default_ai_timeout_seconds)
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def history_dir(self) -> Path:
        return self.data_dir / "history"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def ensure_dirs(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["project_root"] = str(self.project_root)
        data["data_dir"] = str(self.data_dir)
        data["database_url"] = mask_database_url(self.database_url) if self.database_url else str(self.default_sqlite_database_path)
        data["feishu_app_secret"] = "***" if self.feishu_app_secret else None
        data.pop("watchlist_commentary_feishu_chat_id", None)
        data["client_auth_secret"] = "***"
        data["ai_command"] = "***" if self.ai_command else None
        data["zhipu_api_key"] = "***" if self.zhipu_api_key else None
        backend = self.resolved_ai_backend
        data["ai"] = {
            "configured": backend != "rules_fallback",
            "provider": backend,
            "requested_provider": self.ai_provider,
            "model": self.zhipu_model if backend == "zhipu" else None,
        }
        return data

    @property
    def resolved_ai_backend(self) -> str:
        if self.ai_provider == "rules":
            return "rules_fallback"
        if self.ai_provider == "zhipu":
            return "zhipu" if self.zhipu_api_key else "rules_fallback"
        if self.ai_provider == "command":
            return "external_command" if self.ai_command else "rules_fallback"
        if self.zhipu_api_key:
            return "zhipu"
        if self.ai_command:
            return "external_command"
        return "rules_fallback"

    @property
    def default_sqlite_database_path(self) -> Path:
        return self.data_dir / "stock_lab.sqlite3"


def mask_database_url(url: str) -> str:
    if "://" not in url:
        return url
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        return url
    hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    netloc = f"***@{hostname}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


CONFIG = AppConfig()
