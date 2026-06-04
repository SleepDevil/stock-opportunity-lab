from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date, timedelta
import io
import math
import re
from typing import Any, Protocol

import pandas as pd

from app.services.data_provider import normalize_stock_code


REPORT_TYPES = ("资产负债表", "利润表", "现金流量表")


class FinancialDataProvider(Protocol):
    def financial_report(self, symbol: str, statement: str) -> pd.DataFrame:
        ...

    def financial_indicators(self, symbol: str, start_year: str) -> pd.DataFrame:
        ...

    def disclosure_reports(
        self,
        symbol: str,
        *,
        category: str,
        start_date: str,
        end_date: str,
        keyword: str = "",
    ) -> pd.DataFrame:
        ...


@dataclass
class AkShareFinancialProvider:
    def _ak(self):
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AkShare is not installed. Run `npm run setup` first.") from exc
        return ak

    def financial_report(self, symbol: str, statement: str) -> pd.DataFrame:
        if statement not in REPORT_TYPES:
            raise ValueError(f"Unsupported financial statement: {statement}")
        with quiet_akshare_output():
            return self._ak().stock_financial_report_sina(stock=sina_stock_symbol(symbol), symbol=statement)

    def financial_indicators(self, symbol: str, start_year: str) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_financial_analysis_indicator(symbol=normalize_stock_code(symbol), start_year=start_year)

    def disclosure_reports(
        self,
        symbol: str,
        *,
        category: str,
        start_date: str,
        end_date: str,
        keyword: str = "",
    ) -> pd.DataFrame:
        with quiet_akshare_output():
            return self._ak().stock_zh_a_disclosure_report_cninfo(
                symbol=normalize_stock_code(symbol),
                market="沪深京",
                keyword=keyword,
                category=category,
                start_date=start_date,
                end_date=end_date,
            )


class quiet_akshare_output:
    def __enter__(self):
        self._stdout = redirect_stdout(io.StringIO())
        self._stderr = redirect_stderr(io.StringIO())
        self._stdout.__enter__()
        self._stderr.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stderr.__exit__(exc_type, exc, tb)
        self._stdout.__exit__(exc_type, exc, tb)
        return False


def run_stock_financials(
    provider: FinancialDataProvider,
    symbol: str,
    years: int = 5,
    refresh: bool = False,
) -> dict[str, Any]:
    _ = refresh
    code = normalize_stock_code(symbol)
    window_years = max(1, min(int(years), 10))
    start_year = str(max(1900, date.today().year - window_years))
    start_date = (date.today() - timedelta(days=window_years * 366)).strftime("%Y%m%d")
    end_date = date.today().strftime("%Y%m%d")

    profit = frame_by_report_date(provider.financial_report(code, "利润表"))
    balance = frame_by_report_date(provider.financial_report(code, "资产负债表"))
    cash = frame_by_report_date(provider.financial_report(code, "现金流量表"))
    indicators = indicator_rows(provider.financial_indicators(code, start_year))
    disclosures = disclosure_rows(
        provider.disclosure_reports(
            code,
            category="年报",
            start_date=start_date,
            end_date=end_date,
        )
    )

    indicator_map = {row["report_date"]: row for row in indicators}
    report_dates = sorted(set(profit) | set(balance) | set(cash) | set(indicator_map), reverse=True)
    max_rows = window_years * 4
    statements = [
        statement_row(
            report_date=report_date,
            profit=profit.get(report_date),
            balance=balance.get(report_date),
            cash=cash.get(report_date),
            indicators=indicator_map.get(report_date),
        )
        for report_date in report_dates[:max_rows]
    ]
    indicators = enrich_indicator_rows(indicators, statements)

    return {
        "code": code,
        "years": window_years,
        "source": "akshare:sina_finance+cninfo",
        "summary": financial_summary(statements),
        "statements": statements,
        "indicators": indicators[:max_rows],
        "disclosures": disclosures[:20],
        "disclaimer": "财务报表和公告来自 AkShare 聚合的新浪财经与巨潮资讯公开数据，仅用于研究展示。",
    }


def frame_by_report_date(df: pd.DataFrame) -> dict[str, pd.Series]:
    if df.empty or "报告日" not in df.columns:
        return {}
    result: dict[str, pd.Series] = {}
    for _, row in df.iterrows():
        report_date = normalize_report_date(row.get("报告日"))
        if report_date:
            result.setdefault(report_date, row)
    return result


def indicator_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        report_date = normalize_report_date(row.get("日期"))
        if not report_date:
            continue
        rows.append(
            {
                "report_date": report_date,
                "gross_margin": safe_number(row.get("销售毛利率(%)")),
                "roe": safe_number(first_existing(row, "净资产收益率(%)", "加权净资产收益率(%)")),
                "asset_liability_ratio": safe_number(row.get("资产负债率(%)")),
                "revenue_growth": safe_number(row.get("主营业务收入增长率(%)")),
                "net_profit_growth": safe_number(row.get("净利润增长率(%)")),
                "current_ratio": safe_number(row.get("流动比率")),
                "quick_ratio": safe_number(row.get("速动比率")),
            }
        )
    rows.sort(key=lambda item: item["report_date"], reverse=True)
    return rows


def disclosure_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        title = text_value(row.get("公告标题"))
        url = text_value(row.get("公告链接"))
        if not title or not url:
            continue
        rows.append(
            {
                "code": normalize_stock_code(row.get("代码", "")),
                "name": text_value(row.get("简称")),
                "title": title,
                "publish_date": display_report_date(row.get("公告时间")),
                "url": url,
            }
        )
    rows.sort(key=lambda item: item.get("publish_date") or "", reverse=True)
    return rows


def statement_row(
    *,
    report_date: str,
    profit: pd.Series | None,
    balance: pd.Series | None,
    cash: pd.Series | None,
    indicators: dict[str, Any] | None,
) -> dict[str, Any]:
    total_assets = safe_number(first_existing(balance, "资产总计", "资产合计", "总资产"))
    total_liabilities = safe_number(first_existing(balance, "负债合计", "负债总计", "总负债"))
    ratio = None
    if total_assets and total_liabilities is not None:
        ratio = round(total_liabilities / total_assets * 100, 2)
    if indicators and indicators.get("asset_liability_ratio") is not None:
        ratio = indicators["asset_liability_ratio"]
    gross_margin = (indicators or {}).get("gross_margin")
    if gross_margin is None:
        gross_margin = gross_margin_from_profit(profit)

    return {
        "report_date": report_date,
        "announcement_date": normalize_report_date(first_existing(profit, "公告日期")),
        "revenue": safe_number(first_existing(profit, "营业总收入", "营业收入", "主营业务收入")),
        "net_profit": safe_number(first_existing(profit, "归属于母公司所有者的净利润", "净利润")),
        "operating_profit": safe_number(first_existing(profit, "营业利润")),
        "eps": safe_number(first_existing(profit, "基本每股收益", "摊薄每股收益(元)", "加权每股收益(元)")),
        "operating_cash_flow": safe_number(first_existing(cash, "经营活动产生的现金流量净额", "经营现金净流量")),
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "asset_liability_ratio": ratio,
        "gross_margin": gross_margin,
        "roe": (indicators or {}).get("roe"),
        "revenue_growth": (indicators or {}).get("revenue_growth"),
        "net_profit_growth": (indicators or {}).get("net_profit_growth"),
        "audit_status": text_value(first_existing(profit, "是否审计")),
    }


def enrich_indicator_rows(indicators: list[dict[str, Any]], statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    statement_map = {row["report_date"]: row for row in statements}
    enriched: list[dict[str, Any]] = []
    for row in indicators:
        copy = row.copy()
        statement = statement_map.get(copy["report_date"])
        if statement and copy.get("gross_margin") is None:
            copy["gross_margin"] = statement.get("gross_margin")
        enriched.append(copy)
    return enriched


def financial_summary(statements: list[dict[str, Any]]) -> dict[str, Any]:
    latest = next((row for row in statements if row.get("report_date")), {})
    revenue = safe_number(latest.get("revenue"))
    net_profit = safe_number(latest.get("net_profit"))
    operating_cash_flow = safe_number(latest.get("operating_cash_flow"))
    roe = safe_number(latest.get("roe"))
    asset_liability_ratio = safe_number(latest.get("asset_liability_ratio"))
    revenue_growth = safe_number(latest.get("revenue_growth"))
    net_profit_growth = safe_number(latest.get("net_profit_growth"))
    bullets: list[str] = []
    if revenue_growth is not None:
        bullets.append(f"营收同比 {revenue_growth:.2f}%。")
    if net_profit_growth is not None:
        bullets.append(f"净利润同比 {net_profit_growth:.2f}%。")
    if net_profit is not None and operating_cash_flow is not None:
        cash_ratio = operating_cash_flow / net_profit if net_profit else None
        if cash_ratio is not None:
            bullets.append(f"经营现金流/净利润约 {cash_ratio:.2f}。")
    if asset_liability_ratio is not None:
        bullets.append(f"资产负债率 {asset_liability_ratio:.2f}%。")

    tone = "neutral"
    if net_profit is not None and net_profit <= 0:
        tone = "weak"
    elif operating_cash_flow is not None and net_profit is not None and net_profit > 0 and operating_cash_flow < 0:
        tone = "watch_cash"
    elif roe is not None and roe >= 8 and (net_profit_growth is None or net_profit_growth >= 0):
        tone = "healthy"

    return {
        "latest_report_date": latest.get("report_date"),
        "latest_revenue": revenue,
        "latest_net_profit": net_profit,
        "latest_operating_cash_flow": operating_cash_flow,
        "latest_roe": roe,
        "latest_asset_liability_ratio": asset_liability_ratio,
        "latest_revenue_growth": revenue_growth,
        "latest_net_profit_growth": net_profit_growth,
        "tone": tone,
        "bullets": bullets,
    }


def first_existing(row: pd.Series | dict[str, Any] | None, *columns: str) -> Any:
    if row is None:
        return None
    for column in columns:
        if column in row:
            value = row[column]
            if pd.notna(value):
                return value
    return None


def gross_margin_from_profit(row: pd.Series | None) -> float | None:
    revenue = safe_number(first_existing(row, "营业总收入", "营业收入", "主营业务收入"))
    cost = safe_number(first_existing(row, "营业成本", "主营业务成本"))
    if revenue is None or revenue <= 0 or cost is None:
        return None
    return round((revenue - cost) / revenue * 100, 2)


def safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 2)


def normalize_report_date(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return None


def display_report_date(value: Any) -> str | None:
    normalized = normalize_report_date(value)
    if not normalized:
        return None
    return f"{normalized[:4]}-{normalized[4:6]}-{normalized[6:]}"


def text_value(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def sina_stock_symbol(symbol: str) -> str:
    code = normalize_stock_code(symbol)
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("4", "8", "9")):
        return f"bj{code}"
    return f"sz{code}"
