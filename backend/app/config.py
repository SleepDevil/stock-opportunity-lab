from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    override = os.getenv("STOCK_LAB_DATA_DIR")
    return Path(override).expanduser() if override else PROJECT_ROOT / "data"


def default_database_url() -> str | None:
    return os.getenv("STOCK_LAB_DATABASE_URL")


@dataclass
class ScreenConfig:
    max_candidates: int = 30
    min_price: float = 3.0
    max_price: float = 300.0
    min_amount: float = 200_000_000.0
    min_turnover: float = 3.0
    max_turnover: float = 15.0
    min_volume_ratio: float = 1.2
    min_float_market_cap: float = 3_000_000_000.0
    max_float_market_cap: float = 50_000_000_000.0
    min_total_market_cap: float = 5_000_000_000.0
    max_total_market_cap: float = 100_000_000_000.0
    min_pct_change: float = -6.0
    max_pct_change: float = 9.5
    exclude_name_regex: str = "ST|退|N|C"
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
    entry_discount: float = 0.012
    entry_premium: float = 0.012
    breakout_premium: float = 0.026
    avoid_gap_up: float = 0.045
    stop_loss: float = 0.055
    take_profit: float = 0.085
    max_single_position_pct: float = 12.0
    risk_per_trade_pct: float = 1.0


@dataclass
class AppConfig:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = field(default_factory=default_data_dir)
    database_url: str | None = field(default_factory=default_database_url)
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
        return data

    @property
    def default_sqlite_database_path(self) -> Path:
        return self.data_dir / "stock_lab.sqlite3"


def mask_database_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


CONFIG = AppConfig()
