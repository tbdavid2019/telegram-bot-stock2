"""Quantitative stock-analysis tools used by the conversational agent.

The functions in this module are deliberately synchronous because LangChain
tools may be invoked by either a synchronous or asynchronous graph. Telegram
handlers call them through an executor (see ``handlers/stock_cmds.py``).
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import yfinance as yf

try:
    from langchain_core.tools import tool
except ImportError:  # pragma: no cover - useful for lightweight local checks
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

from tools.stock import resolve_ticker


logger = logging.getLogger(__name__)


def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    """Return a finite float from yfinance/pandas values."""
    if value is None:
        return default
    if isinstance(value, pd.Series):
        value = value.iloc[-1] if not value.empty else None
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _flatten_columns(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance's single- and multi-ticker column layouts."""
    result = data.copy()
    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)
    elif len(result.columns) and isinstance(result.columns[0], tuple):
        result.columns = [column[0] for column in result.columns]
    return result


def _history(ticker: str, period: str = "2y") -> pd.DataFrame:
    data = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=False)
    if data is None or data.empty:
        if ".TW" in ticker.upper() or ".TWO" in ticker.upper() or any(c.isdigit() for c in ticker):
            from tools.tw_stocker import fetch_tw_stocker_df
            tw_df = fetch_tw_stocker_df(ticker)
            if tw_df is not None and not tw_df.empty:
                return tw_df.copy()
        return pd.DataFrame()
    data = _flatten_columns(data)
    for column in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
        if column in data:
            data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna(subset=["Close"])


def _info(ticker: str) -> Dict[str, Any]:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception as exc:
        logger.warning("Unable to read yfinance info for %s: %s", ticker, exc)
        return {}


def _latest_statement_value(statement: Any, names: Iterable[str]) -> Optional[float]:
    if not isinstance(statement, pd.DataFrame) or statement.empty:
        return None
    wanted = {name.lower().replace(" ", "") for name in names}
    for index in statement.index:
        normalized = str(index).lower().replace(" ", "")
        if normalized in wanted:
            row = pd.to_numeric(statement.loc[index], errors="coerce").dropna()
            if not row.empty:
                return _number(row.iloc[0])
    return None


def _safe_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _safe_date(value[0]) if value else None
    try:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            return None
        return timestamp.strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def _vcp_diagnostic(history: pd.DataFrame) -> Dict[str, Any]:
    close = history["Close"]
    high = history["High"] if "High" in history else close
    low = history["Low"] if "Low" in history else close
    volume = history["Volume"] if "Volume" in history else pd.Series(index=history.index, dtype=float)
    ranges = ((high - low) / close.replace(0, pd.NA)).dropna()
    contractions: List[float] = []
    for window in (5, 10, 20):
        if len(ranges) >= window * 2:
            recent = _number(ranges.tail(window).mean())
            prior = _number(ranges.iloc[-window * 2:-window].mean())
            if recent is not None and prior and prior > 0:
                contractions.append(round(recent / prior, 3))
    volume_ratio = None
    if len(volume.dropna()) >= 50 and _number(volume.tail(50).mean(), 0) > 0:
        volume_ratio = round(_number(volume.tail(10).mean(), 0) / _number(volume.tail(50).mean(), 1), 3)
    contraction_pass = len(contractions) >= 2 and all(value < 1 for value in contractions)
    return {
        "detected": bool(contraction_pass and (volume_ratio is None or volume_ratio < 1)),
        "range_contraction_ratios": contractions,
        "volume_10d_vs_50d": volume_ratio,
        "note": "VCP is a quantitative screening heuristic; confirm the base and pivot visually.",
    }


@tool
def get_sepa_analysis(ticker: str) -> Dict[str, Any]:
    """Evaluate Mark Minervini's 8-point trend template and VCP heuristics for a ticker or company name."""
    ticker = resolve_ticker(ticker)
    history = _history(ticker, "2y")
    if history.empty or len(history) < 200:
        return {"stock": ticker, "error": f"資料不足：{ticker} 的 SEPA 分析至少需要約 200 個交易日歷史價格。"}

    close = history["Close"]
    moving = {period: close.rolling(period).mean() for period in (50, 150, 200)}
    latest = _number(close.iloc[-1], 0)
    ma50 = _number(moving[50].iloc[-1], 0)
    ma150 = _number(moving[150].iloc[-1], 0)
    ma200 = _number(moving[200].iloc[-1], 0)
    ma200_month_ago = _number(moving[200].iloc[-21], 0)
    high_52 = _number(close.tail(252).max(), latest)
    low_52 = _number(close.tail(252).min(), latest)

    relative_return: Optional[float] = None
    spy_return: Optional[float] = None
    try:
        spy = _history("SPY", "2y")["Close"]
        if len(spy) >= 63 and len(close) >= 63:
            spy_return = _number(spy.iloc[-1] / spy.iloc[-63] - 1)
            relative_return = _number(close.iloc[-1] / close.iloc[-63] - 1)
    except Exception as exc:
        logger.info("Relative-strength benchmark unavailable: %s", exc)

    rules = [
        {"rule": 1, "criterion": "股價高於 150 日均線與 200 日均線", "passed": latest > ma150 and latest > ma200},
        {"rule": 2, "criterion": "150 日均線高於 200 日均線", "passed": ma150 > ma200},
        {"rule": 3, "criterion": "200 日均線近一個月上升", "passed": ma200 > ma200_month_ago},
        {"rule": 4, "criterion": "50 日均線高於 150 日均線與 200 日均線", "passed": ma50 > ma150 and ma50 > ma200},
        {"rule": 5, "criterion": "股價高於 52 週低點至少 25%", "passed": latest >= low_52 * 1.25},
        {"rule": 6, "criterion": "股價位於 52 週高點 25% 範圍內", "passed": latest >= high_52 * 0.75},
        {"rule": 7, "criterion": "近三個月表現不弱於 SPY", "passed": relative_return is not None and spy_return is not None and relative_return >= spy_return},
        {"rule": 8, "criterion": "股價站上 50 日均線，具備 Stage 2 動能", "passed": latest > ma50},
    ]
    passed = sum(1 for rule in rules if rule["passed"])
    pivot = _number(close.tail(20).max(), latest)
    atr = _number((history["High"] - history["Low"]).tail(14).mean(), latest * 0.03) or latest * 0.03
    stop_7 = pivot * 0.93
    stop_atr = pivot - 2 * atr

    return {
        "stock": ticker,
        "stage": "Stage 2 上升趨勢" if passed >= 6 and latest > ma200 else "未確認 Stage 2",
        "template_score": f"{passed}/8",
        "rules": rules,
        "metrics": {
            "price": round(latest, 4),
            "ma50": round(ma50, 4),
            "ma150": round(ma150, 4),
            "ma200": round(ma200, 4),
            "52_week_high": round(high_52, 4),
            "52_week_low": round(low_52, 4),
            "relative_3m_return": round(relative_return * 100, 2) if relative_return is not None else None,
            "spy_3m_return": round(spy_return * 100, 2) if spy_return is not None else None,
        },
        "pivot_entry": round(pivot, 4),
        "risk_stops": {
            "7_percent_stop": round(stop_7, 4),
            "2_atr_stop": round(max(0, stop_atr), 4),
        },
        "vcp": _vcp_diagnostic(history),
        "failed_conditions": [rule["criterion"] for rule in rules if not rule["passed"]],
        "disclaimer": "SEPA 是技術篩選，不是投資建議；請搭配成交量、基本面與個人風險管理判斷。",
    }


def _risk_free_rate() -> Optional[float]:
    try:
        history = _history("^TNX", "1mo")
        if not history.empty:
            quote = _number(history["Close"].iloc[-1])
            return quote / 100 if quote is not None else None
    except Exception as exc:
        logger.warning("Unable to read ^TNX: %s", exc)
    return None


def _fcf_from_yfinance(stock: yf.Ticker, info: Dict[str, Any]) -> Optional[float]:
    for key in ("freeCashflow", "operatingCashflow"):
        value = _number(info.get(key))
        if value is not None and key == "freeCashflow":
            return value
    try:
        cashflow = stock.cashflow
        value = _latest_statement_value(cashflow, ("Free Cash Flow", "FreeCashFlow"))
        if value is not None:
            return value
        operating = _latest_statement_value(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"))
        capex = _latest_statement_value(cashflow, ("Capital Expenditure", "Capital Expenditures"))
        if operating is not None and capex is not None:
            return operating + capex if capex < 0 else operating - capex
    except Exception as exc:
        logger.info("Unable to read cash flow for DCF: %s", exc)
    return None


@tool
def get_dcf_valuation(
    ticker: str,
    terminal_growth: float = 0.03,
    equity_risk_premium: float = 0.055,
) -> Dict[str, Any]:
    """Calculate a five-year FCFF DCF with ^TNX-based WACC and sensitivity for a ticker or company name."""
    ticker = resolve_ticker(ticker)
    stock = yf.Ticker(ticker)
    info = _info(ticker)
    price = _number(info.get("currentPrice"))
    if price is None:
        history = _history(ticker, "1mo")
        price = _number(history["Close"].iloc[-1]) if not history.empty else None
    market_cap = _number(info.get("marketCap"))
    base_fcf = _fcf_from_yfinance(stock, info)
    revenue = _number(info.get("totalRevenue"))
    if base_fcf is None or base_fcf <= 0 or not market_cap or not price:
        revenue_multiple = _number(info.get("priceToSalesTrailing12Months"))
        if revenue_multiple is None and revenue and market_cap:
            revenue_multiple = market_cap / revenue
        return {
            "stock": ticker,
            "method": "relative_revenue_fallback",
            "current_price": price,
            "revenue": revenue,
            "price_to_sales": revenue_multiple,
            "error": "自由現金流為負值或資料不足，無法進行標準 DCF；請以 EV/Revenue 或 P/S 交叉估值。",
            "limitation": "早期或虧損企業的營收倍數不代表內在價值，結果不應視為 DCF 公允價。",
        }

    rf = _risk_free_rate()
    rf_source = "^TNX" if rf is not None else "fallback 4.0% (live ^TNX unavailable)"
    rf = rf if rf is not None else 0.04
    beta = _number(info.get("beta"), 1.0) or 1.0
    cost_equity = rf + beta * equity_risk_premium
    debt = _number(info.get("totalDebt"), 0) or 0
    equity = market_cap
    tax_rate = _number(info.get("effectiveTaxRate"), 0.21) or 0.21
    interest_expense = _number(info.get("interestExpense"), 0) or 0
    cost_debt = abs(interest_expense / debt) if debt and interest_expense else 0.04
    total_capital = equity + debt
    wacc = (equity / total_capital) * cost_equity + (debt / total_capital) * cost_debt * (1 - tax_rate)
    wacc = max(wacc, rf + 0.01)
    growth = _number(info.get("revenueGrowth"), 0.08) or 0.08
    growth = max(-0.05, min(growth, 0.30))
    operating_margin = _number(info.get("operatingMargins"), 0.15) or 0.15
    base_margin = max(0.02, min(operating_margin, 0.50))
    shares = _number(info.get("sharesOutstanding"))
    if not shares:
        shares = market_cap / price

    def scenario_value(growth_rate: float, margin: float, discount: float, terminal: float) -> Optional[float]:
        if discount <= terminal:
            return None
        cashflows = []
        current = base_fcf
        for year in range(1, 6):
            current *= 1 + growth_rate
            # Keep the scenario transparent: cash flow growth is blended with margin quality.
            current *= 1 + (margin - base_margin) * 0.5
            cashflows.append(current)
        terminal_value = cashflows[-1] * (1 + terminal) / (discount - terminal)
        enterprise_value = sum(value / (1 + discount) ** year for year, value in enumerate(cashflows, 1))
        enterprise_value += terminal_value / (1 + discount) ** 5
        equity_value = enterprise_value - debt + (_number(info.get("totalCash"), 0) or 0)
        return equity_value / shares if shares else None

    scenarios = {
        "bear": scenario_value(max(-0.05, growth - 0.08), max(0.02, base_margin - 0.04), wacc + 0.02, max(0.01, terminal_growth - 0.01)),
        "base": scenario_value(growth, base_margin, wacc, terminal_growth),
        "bull": scenario_value(min(0.35, growth + 0.08), min(0.60, base_margin + 0.04), max(rf + 0.02, wacc - 0.02), terminal_growth + 0.01),
    }
    wacc_values = [max(0.01, wacc - 0.02), wacc, wacc + 0.02]
    terminal_values = [max(0, terminal_growth - 0.01), terminal_growth, terminal_growth + 0.01]
    sensitivity = {
        f"wacc_{round(rate * 100, 2)}%": {
            f"terminal_growth_{round(g * 100, 2)}%": scenario_value(growth, base_margin, rate, g)
            for g in terminal_values
        }
        for rate in wacc_values
    }
    return {
        "stock": ticker,
        "method": "5-year FCFF DCF",
        "current_price": round(price, 4),
        "risk_free_rate": round(rf * 100, 3),
        "risk_free_rate_source": rf_source,
        "beta": round(beta, 3),
        "wacc": round(wacc * 100, 3),
        "assumptions": {"base_fcf": base_fcf, "growth": growth, "terminal_growth": terminal_growth, "tax_rate": tax_rate},
        "projected_fair_value_per_share": {key: round(value, 4) if value is not None else None for key, value in scenarios.items()},
        "sensitivity_matrix": sensitivity,
        "margin_of_safety_at_base": round((scenarios["base"] / price - 1) * 100, 2) if scenarios["base"] else None,
        "disclaimer": "DCF 對成長率、WACC 與終值高度敏感；這是估值模型，不是投資建議。",
    }


def _earnings_rows(stock: yf.Ticker) -> List[Dict[str, Any]]:
    try:
        dates = stock.earnings_dates
        if not isinstance(dates, pd.DataFrame) or dates.empty:
            return []
        rows = []
        for index, row in dates.head(8).iterrows():
            rows.append({
                "date": _safe_date(index),
                "eps_estimate": _number(row.get("EPS Estimate")),
                "reported_eps": _number(row.get("Reported EPS")),
                "surprise_percent": _number(row.get("Surprise(%)")),
                "revenue_estimate": _number(row.get("Revenue Estimate")),
                "reported_revenue": _number(row.get("Reported Revenue")),
            })
        return rows
    except Exception as exc:
        logger.info("Unable to read earnings dates: %s", exc)
        return []


@tool
def get_earnings_briefing(ticker: str) -> Dict[str, Any]:
    """Return upcoming earnings estimates and the latest four surprise results for a ticker or company name."""
    ticker = resolve_ticker(ticker)
    stock = yf.Ticker(ticker)
    info = _info(ticker)
    rows = _earnings_rows(stock)
    now = dt.datetime.now(dt.timezone.utc).date()
    upcoming = [row for row in rows if row.get("date") and row["date"] >= now.isoformat()]
    historical = [row for row in rows if row not in upcoming and (row.get("reported_eps") is not None or row.get("surprise_percent") is not None)][:4]
    calendar_date = upcoming[0]["date"] if upcoming else None
    try:
        calendar = stock.calendar
        if isinstance(calendar, dict):
            calendar_date = calendar_date or _safe_date(calendar.get("Earnings Date"))
        elif isinstance(calendar, pd.DataFrame) and "Earnings Date" in calendar.index:
            calendar_date = calendar_date or _safe_date(calendar.loc["Earnings Date"].iloc[0])
    except Exception:
        pass
    beats = [row for row in historical if row.get("surprise_percent") is not None and row["surprise_percent"] > 0]
    return {
        "stock": ticker,
        "upcoming_earnings_date": calendar_date,
        "consensus": {
            "eps": upcoming[0].get("eps_estimate") if upcoming else None,
            "revenue": upcoming[0].get("revenue_estimate") if upcoming else None,
            "forward_eps": _number(info.get("forwardEps")),
            "analyst_target_mean": _number(info.get("targetMeanPrice")),
            "analyst_target_high": _number(info.get("targetHighPrice")),
            "analyst_target_low": _number(info.get("targetLowPrice")),
        },
        "last_four_quarters": historical,
        "beat_rate_last_four": round(len(beats) / len(historical) * 100, 2) if historical else None,
        "note": "缺少 yfinance 估計值時會保留 null，不以模型猜測補值。",
    }


@tool
def get_correlation_analysis(tickers: str) -> Dict[str, Any]:
    """Compute 90-trading-day return correlations and SPY betas for 2-5 tickers or company names."""
    raw_symbols = [item.strip() for item in tickers.replace("，", ",").split(",") if item.strip()]
    symbols = [resolve_ticker(sym) for sym in raw_symbols]
    if len(symbols) < 2 or len(symbols) > 5:
        return {"error": "請提供 2 至 5 個股票代碼，以逗號分隔，例如：TSLA,NVDA,AAPL。"}
    series: Dict[str, pd.Series] = {}
    for symbol in symbols:
        try:
            history = _history(symbol, "6mo")
            if not history.empty:
                series[symbol] = history["Close"].tail(120).pct_change()
        except Exception as exc:
            logger.warning("Unable to load %s for correlation: %s", symbol, exc)
    if len(series) < 2:
        return {"tickers": symbols, "error": "可用價格資料不足，無法計算相關性。"}
    returns = pd.concat(series, axis=1).dropna(how="all").tail(90)
    correlation = returns.corr().round(4).fillna(0).to_dict()
    benchmark_history = _history("SPY", "6mo")
    benchmark = benchmark_history["Close"].tail(120).pct_change() if not benchmark_history.empty else pd.Series(dtype=float)
    betas = {}
    for symbol in returns.columns:
        paired = pd.concat([returns[symbol], benchmark.rename("SPY")], axis=1).dropna()
        variance = paired["SPY"].var() if not paired.empty else 0
        betas[symbol] = round(paired[symbol].cov(paired["SPY"]) / variance, 4) if variance else None
    return {
        "tickers": list(returns.columns),
        "observations": len(returns),
        "correlation_matrix": correlation,
        "spy_beta": betas,
        "interpretation": "相關係數越接近 1 代表同向波動越強；Beta 高於 1 通常代表相對 SPY 波動較大。",
    }
