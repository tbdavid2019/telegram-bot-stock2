"""Typed boundary helpers for the AI Hedge Fund API v2 service.

The service is external to the bot, so this module keeps request construction,
response lookup, and HTTP error handling in one place.  Telegram handlers can
then focus on user interaction and presentation.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

import httpx

from config import (
    AI2_API_URL,
    AI2_BASE_URL,
    AI2_BACKTEST_GRID_URL,
    AI2_BACKTEST_RUN_URL,
    AI2_HEALTH_URL,
    AI2_MODEL_NAME,
    AI2_MODEL_PROVIDER,
    AI2_ROUND_TABLE_URL,
    AI2_TIMEOUT,
)


ANALYST_PERSONAS = {
    "warren_buffett": ("👴", "華倫·巴菲特 (Warren Buffett)"),
    "charlie_munger": ("🧓", "查理·蒙格 (Charlie Munger)"),
    "ben_graham": ("📚", "班傑明·葛拉漢 (Ben Graham)"),
    "cathie_wood": ("👩‍💼", "凱西·伍德 (Cathie Wood)"),
    "bill_ackman": ("🦈", "比爾·艾克曼 (Bill Ackman)"),
    "nancy_pelosi": ("🏛️", "南西·裴洛西 (Nancy Pelosi)"),
    "michael_burry": ("👁️", "邁克爾·貝瑞 (Michael Burry)"),
    "peter_lynch": ("🛍️", "彼得·林區 (Peter Lynch)"),
    "phil_fisher": ("🔍", "菲利普·費雪 (Phil Fisher)"),
    "wsb": ("🦍", "華爾街賭場 (WallStreetBets)"),
    "technical_analyst": ("📉", "技術分析師 (Technicals)"),
    "fundamentals_analyst": ("📈", "基本面分析師 (Fundamentals)"),
    "sentiment_analyst": ("🌐", "市場情緒分析師 (Sentiment)"),
    "valuation_analyst": ("⚖️", "估值分析師 (Valuation)"),
    "stanley_druckenmiller": ("🌍", "史丹利·杜肯米勒 (Stanley Druckenmiller)"),
    "decision_model": ("🧠", "Jev 決策模型 (JEV Decision Model)"),
}
ALL_ANALYST_KEYS = tuple(ANALYST_PERSONAS)


class HedgeFundAPIError(ValueError):
    """Raised when the API contract or an API response cannot be used safely."""

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _normalise_tickers(tickers: str | Sequence[str]) -> list[str]:
    if isinstance(tickers, str):
        values = tickers.split(",")
    else:
        try:
            values = list(tickers)
        except TypeError as exc:
            raise HedgeFundAPIError("tickers 必須是字串或字串陣列") from exc
    result = [str(item).strip() for item in values if str(item).strip()]
    if not result:
        raise HedgeFundAPIError("至少需要一個股票代碼")
    return result


def _normalise_analysts(selected_analysts: Iterable[str] | None) -> list[str]:
    values = list(ALL_ANALYST_KEYS) if selected_analysts is None else list(selected_analysts)
    if not all(isinstance(item, str) for item in values):
        raise HedgeFundAPIError("selectedAnalysts 必須是分析師 key 字串陣列")
    unknown = sorted(set(values) - set(ALL_ANALYST_KEYS))
    if unknown:
        raise HedgeFundAPIError(f"未知的分析師 key：{', '.join(unknown)}")
    return values


def _validate_date(value: str, field_name: str) -> str:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HedgeFundAPIError(f"{field_name} 必須使用 YYYY-MM-DD") from exc
    return value


def _validate_rounds(rounds: int, field_name: str) -> int:
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1 or rounds > 3:
        raise HedgeFundAPIError(f"{field_name} 必須是 1 到 3 的整數")
    return rounds


def _validate_portfolio(portfolio: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if portfolio is None:
        return None
    if not isinstance(portfolio, Mapping):
        raise HedgeFundAPIError("portfolio 必須是物件")
    required = {"as_of", "cash", "currency", "positions"}
    missing = sorted(required - set(portfolio))
    if missing:
        raise HedgeFundAPIError(f"portfolio 缺少欄位：{', '.join(missing)}")
    _validate_date(str(portfolio["as_of"]), "portfolio.as_of")
    if isinstance(portfolio["cash"], bool) or not isinstance(portfolio["cash"], (int, float)):
        raise HedgeFundAPIError("portfolio.cash 必須是非負數字")
    if portfolio["cash"] < 0:
        raise HedgeFundAPIError("portfolio.cash 必須是非負數字")
    if not re.fullmatch(r"[A-Za-z]{3}", str(portfolio["currency"])):
        raise HedgeFundAPIError("portfolio.currency 必須是 ISO 4217 三碼貨幣")
    if not isinstance(portfolio["positions"], list):
        raise HedgeFundAPIError("portfolio.positions 必須是陣列")
    for position in portfolio["positions"]:
        if not isinstance(position, Mapping):
            raise HedgeFundAPIError("portfolio.positions 的每一項必須是物件")
        position_required = {"ticker", "quantity", "average_entry_price", "currency"}
        missing_position = sorted(position_required - set(position))
        if missing_position:
            raise HedgeFundAPIError(
                f"portfolio position 缺少欄位：{', '.join(missing_position)}"
            )
        if not re.fullmatch(r"[A-Za-z]{3}", str(position["currency"])):
            raise HedgeFundAPIError("position.currency 必須是 ISO 4217 三碼貨幣")
        if not isinstance(position["ticker"], str) or not position["ticker"].strip():
            raise HedgeFundAPIError("position.ticker 不可為空")
        if isinstance(position["quantity"], bool) or not isinstance(position["quantity"], (int, float)):
            raise HedgeFundAPIError("position.quantity 必須是數字")
        if isinstance(position["average_entry_price"], bool) or not isinstance(
            position["average_entry_price"], (int, float)
        ):
            raise HedgeFundAPIError("position.average_entry_price 必須是數字")
        if position["average_entry_price"] < 0:
            raise HedgeFundAPIError("position.average_entry_price 必須是非負數")
    return dict(portfolio)


def build_analysis_payload(
    tickers: str | Sequence[str],
    *,
    selected_analysts: Iterable[str] | None = None,
    model_name: str = AI2_MODEL_NAME,
    model_provider: str = AI2_MODEL_PROVIDER,
    enable_round_table: bool = True,
    round_table_rounds: int = 2,
    initial_cash: float = 100000,
    portfolio: Mapping[str, Any] | None = None,
    point_in_time: bool = False,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Build and validate a v2 ``/api/analysis`` request."""

    if not isinstance(model_name, str) or not model_name.strip():
        raise HedgeFundAPIError("modelName 不可為空")
    if not isinstance(model_provider, str) or not model_provider.strip():
        raise HedgeFundAPIError("modelProvider 不可為空")
    if isinstance(initial_cash, bool) or not isinstance(initial_cash, (int, float)) or initial_cash < 100.0:
        raise HedgeFundAPIError("initialCash 必須為大於或等於 100.0 的數字（最低門檻 100.0）")

    payload: dict[str, Any] = {
        "tickers": ",".join(_normalise_tickers(tickers)),
        "selectedAnalysts": _normalise_analysts(selected_analysts),
        "modelName": model_name.strip(),
        "modelProvider": model_provider.strip(),
        "enableRoundTable": bool(enable_round_table),
        "roundTableRounds": _validate_rounds(round_table_rounds, "roundTableRounds"),
        "initialCash": initial_cash,
    }
    validated_portfolio = _validate_portfolio(portfolio)
    if validated_portfolio is not None:
        payload["portfolio"] = validated_portfolio
    if point_in_time:
        payload["pointInTime"] = True
    if start_date is not None:
        payload["startDate"] = _validate_date(start_date, "startDate")
    if end_date is not None:
        payload["endDate"] = _validate_date(end_date, "endDate")
    return payload


def build_round_table_payload(
    tickers: str | Sequence[str],
    analyst_signals: Mapping[str, Any],
    *,
    model_name: str = "gpt-4o",
    num_rounds: int = 2,
) -> dict[str, Any]:
    """Build and validate a standalone ``/api/round_table`` request."""

    if not isinstance(analyst_signals, Mapping) or not analyst_signals:
        raise HedgeFundAPIError("analystSignals 必須是非空物件")
    if not isinstance(model_name, str) or not model_name.strip():
        raise HedgeFundAPIError("modelName 不可為空")
    return {
        "tickers": ",".join(_normalise_tickers(tickers)),
        "analystSignals": dict(analyst_signals),
        "modelName": model_name.strip(),
        "numRounds": _validate_rounds(num_rounds, "numRounds"),
    }


def build_backtest_payload(
    *,
    run_id: str,
    tickers: str | Sequence[str],
    start_date: str,
    end_date: str,
    cutoff_time_utc: str = "16:00:00Z",
    selected_analysts: Iterable[str] | None = None,
    initial_cash: float = 100000,
    portfolio: Mapping[str, Any] | None = None,
    daily_rebalance_policy: str = "daily",
    transaction_fee_rate: float = 0.001,
    slippage_rate: float = 0.0005,
    margin_ratio: float = 0.5,
) -> dict[str, Any]:
    """Build and validate a resumable ``/api/backtest/grid`` request."""

    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", run_id):
        raise HedgeFundAPIError("runId 只可包含英數字、句點、底線與連字號，長度 1 到 100")
    start_date = _validate_date(start_date, "startDate")
    end_date = _validate_date(end_date, "endDate")
    if start_date > end_date:
        raise HedgeFundAPIError("startDate 不可晚於 endDate")
    if daily_rebalance_policy not in {"daily", "none"}:
        raise HedgeFundAPIError("dailyRebalancePolicy 必須是 daily 或 none")
    for field_name, value in (
        ("transactionFeeRate", transaction_fee_rate),
        ("slippageRate", slippage_rate),
        ("marginRatio", margin_ratio),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise HedgeFundAPIError(f"{field_name} 必須是非負數字")
    if isinstance(initial_cash, bool) or not isinstance(initial_cash, (int, float)) or initial_cash < 100.0:
        raise HedgeFundAPIError("initialCash 必須為大於或等於 100.0 的數字（最低門檻 100.0）")

    payload: dict[str, Any] = {
        "runId": run_id,
        "tickers": list(_normalise_tickers(tickers)) if not isinstance(tickers, str) else ",".join(_normalise_tickers(tickers)),
        "startDate": start_date,
        "endDate": end_date,
        "cutoffTimeUtc": cutoff_time_utc,
        "initialCash": initial_cash,
        "dailyRebalancePolicy": daily_rebalance_policy,
        "transactionFeeRate": transaction_fee_rate,
        "slippageRate": slippage_rate,
        "marginRatio": margin_ratio,
    }
    if selected_analysts is not None:
        payload["selectedAnalysts"] = _normalise_analysts(selected_analysts)
    validated_portfolio = _validate_portfolio(portfolio)
    if validated_portfolio is not None:
        payload["portfolio"] = validated_portfolio
    return payload


def get_symbol_entry(mapping: Mapping[str, Any] | None, symbol: str) -> Any:
    """Return an exact case-insensitive symbol entry without cross-symbol fallback."""

    if not isinstance(mapping, Mapping):
        return None
    expected = symbol.strip().casefold()
    for key, value in mapping.items():
        if str(key).strip().casefold() == expected:
            return value
    return None


def split_message(text: str, max_length: int = 3900) -> list[str]:
    """Split Telegram text at paragraph boundaries while preserving all content."""

    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at < max_length // 2:
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at < max_length // 2:
            split_at = max_length
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


class HedgeFundAPIClient:
    """Small async client for the documented AI Hedge Fund API v2 endpoints."""

    def __init__(self, base_url: str = AI2_BASE_URL, timeout: float = AI2_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if self.base_url == AI2_BASE_URL.rstrip("/"):
            self.analysis_url = AI2_API_URL
            self.analysis_async_url = f"{self.base_url}/api/analysis/async"
            self.task_url = f"{self.base_url}/api/task"
            self.round_table_url = AI2_ROUND_TABLE_URL
            self.backtest_grid_url = AI2_BACKTEST_GRID_URL
            self.backtest_run_url = AI2_BACKTEST_RUN_URL
            self.health_url = AI2_HEALTH_URL
        else:
            self.analysis_url = f"{self.base_url}/api/analysis"
            self.analysis_async_url = f"{self.base_url}/api/analysis/async"
            self.task_url = f"{self.base_url}/api/task"
            self.round_table_url = f"{self.base_url}/api/round_table"
            self.backtest_grid_url = f"{self.base_url}/api/backtest/grid"
            self.backtest_run_url = f"{self.base_url}/api/backtest/runs"
            self.health_url = f"{self.base_url}/api/health"

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        return f"{self.base_url}{path_or_url}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(method, self._url(path), json=payload)
        except httpx.HTTPError as exc:
            raise HedgeFundAPIError(f"AI Hedge Fund API 網路連線失敗：{exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            body = response.text
            raise HedgeFundAPIError(
                "AI Hedge Fund API 回傳非 JSON 內容",
                status_code=response.status_code,
                body=body,
            ) from exc
        if response.status_code >= 400:
            if isinstance(body, Mapping):
                message = str(body.get("error") or body.get("message") or "API 請求失敗")
            else:
                message = "API 請求失敗"
            raise HedgeFundAPIError(message, status_code=response.status_code, body=body)
        if not isinstance(body, dict):
            raise HedgeFundAPIError(
                "AI Hedge Fund API 回傳格式錯誤",
                status_code=response.status_code,
                body=body,
            )
        return body

    async def analyze(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._request("POST", self.analysis_url, payload=payload)

    async def analyze_async(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Submit an equity analysis task in the background (HTTP 202)."""
        return await self._request("POST", self.analysis_async_url, payload=payload)

    async def get_task_status(self, task_id: str) -> dict[str, Any]:
        """Poll async task status and retrieve analysis result."""
        if not isinstance(task_id, str) or not task_id.strip():
            raise HedgeFundAPIError("taskId 不可為空")
        return await self._request("GET", f"{self.task_url.rstrip('/')}/{task_id.strip()}")

    async def round_table(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._request("POST", self.round_table_url, payload=payload)

    async def backtest_grid(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._request("POST", self.backtest_grid_url, payload=payload)

    async def get_backtest_run(self, run_id: str) -> dict[str, Any]:
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", run_id):
            raise HedgeFundAPIError("runId 格式錯誤")
        return await self._request("GET", f"{self.backtest_run_url.rstrip('/')}/{run_id}")

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", self.health_url)


__all__ = [
    "ALL_ANALYST_KEYS",
    "ANALYST_PERSONAS",
    "HedgeFundAPIClient",
    "HedgeFundAPIError",
    "build_analysis_payload",
    "build_backtest_payload",
    "build_round_table_payload",
    "get_symbol_entry",
    "split_message",
]
