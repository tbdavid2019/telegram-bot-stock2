"""Client and LangChain tools for 888 Stock Quant Platform (stockdata.david888.com).

Integrates:
- Macro Risk Regime & Exposure recommendations (0% ~ 100%)
- Triple & Quadruple Resonance stock screening (Xuantie ∩ Institutions ∩ LSTM ∩ TimesFM)
- Google TimesFM 2.5 Foundational Time-Series model predictions & Risk/Reward Ratios
- Xuantie Heavy Sword MA60/120 pullback swing trading signals
- Taiwan Stock Key Broker Branches (主力分點買賣超與集中度)
- Structural Calendars (US Major Earnings, Global Macro CPI/NFP, CME FedWatch, Commodities)

Protected with SingleFlight and TTLCache for multi-user high-concurrency Telegram operations.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlparse, parse_qs
from typing import Any, Dict, List, Optional

import requests

from config import STOCKDATA_BASE_URL
from tools.cache_util import TTLCache, SingleFlight
from tools.telegram_formatter import format_card

try:
    from langchain_core.tools import tool
except ImportError:  # pragma: no cover
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

logger = logging.getLogger(__name__)

# --- Caches & SingleFlight ---
_macro_cache = TTLCache(default_ttl=300.0, max_size=50)       # 5 min
_resonance_cache = TTLCache(default_ttl=600.0, max_size=50)   # 10 min
_timesfm_cache = TTLCache(default_ttl=600.0, max_size=100)    # 10 min
_xuantie_cache = TTLCache(default_ttl=600.0, max_size=50)     # 10 min
_broker_cache = TTLCache(default_ttl=900.0, max_size=200)     # 15 min
_calendar_cache = TTLCache(default_ttl=900.0, max_size=50)    # 15 min

_sd_singleflight = SingleFlight()

REQUEST_TIMEOUT = 10.0
USER_AGENT = "telegram-bot-stock2/2.22 (888 Stock Quant Client)"


def _get_json(endpoint_path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    """Execute GET request against stockdata.david888.com."""
    url = f"{STOCKDATA_BASE_URL.rstrip('/')}/{endpoint_path.lstrip('/')}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"StockData API {endpoint_path} returned {resp.status_code}")
    except Exception as e:
        logger.error(f"StockData API error for {endpoint_path}: {e}")
    return None


# ==========================================
# 1. Macro Regime & Exposure (大盤風控與曝險)
# ==========================================

def fetch_macro_regime(market: str = "tw") -> Dict[str, Any]:
    """Fetch current market risk regime, exposure recommendation, and warnings."""
    m_code = "tw" if "tw" in market.lower() or "台" in market else "us"
    cache_key = f"macro:{m_code}"
    cached = _macro_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/macro/latest", params={"market": m_code})
        if res and res.get("success"):
            res = dict(res)
            requested_market = m_code.upper()
            actual_market = str(res.get("market", "")).upper()
            res["requested_market"] = requested_market
            if actual_market and actual_market != requested_market:
                res["market_mismatch"] = (
                    f"API 市場欄位不一致：請求 {requested_market}，回傳 {actual_market}"
                )
            _macro_cache.set(cache_key, res)
            return res
        stale = _macro_cache.get_stale(cache_key)
        if stale:
            logger.info(f"StockData macro API unavailable; serving stale cache for {m_code}")
            return stale
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_macro_regime_markdown(data: Dict[str, Any]) -> str:
    """Format macro regime into clean Telegram HTML card with pre code block."""
    if not data or not isinstance(data, dict) or not data.get("success"):
        return format_card("大盤風控制度與部位曝險指南", "無大盤風控資料", emoji="🛡️")

    market_code = str(data.get("requested_market") or data.get("market") or "US").upper()
    m_name = "台股市場" if market_code == "TW" else "美股市場"
    regime = data.get("regime_name") or "評估中"
    exposure = data.get("macro_exposure_limit") or data.get("exposure") or 0.0
    exp_pct = int(round(exposure * 100))
    vix = data.get("vix") or 0.0

    # Status badges
    spy_status = "季線上" if data.get("spy_above_ma60") else "跌破季線"
    twii_status = "季線上" if data.get("twii_above_ma60") else "跌破季線"
    sox_status = "季線上" if data.get("sox_above_ma60") else "跌破季線"

    # Exposure bar (prevent negative or overflow)
    filled = max(0, min(10, exp_pct // 10))
    bar = "█" * filled + "░" * (10 - filled)

    card_lines = [
        f"監控市場: {m_name} ({market_code})",
        f"市場狀態: {regime}",
        f"建議曝險: [{bar}] {exp_pct}%",
        "",
        "[核心指數均線狀態]",
        f"台股加權 (^TWII): {twii_status}",
        f"美股標普 (SPY):   {spy_status}",
        f"費城半導 (^SOX): {sox_status}",
        f"VIX 恐慌指數:    {vix:.2f}",
    ]

    if data.get("market_mismatch"):
        card_lines.insert(3, f"市場偏離: {data['market_mismatch']}")

    warnings = data.get("warnings", [])
    if warnings:
        card_lines.append("")
        card_lines.append("[關鍵風控警語]")
        for w in warnings[:3]:
            card_lines.append(f"• {w}")

    footer = "量化建議：請依建議曝險動態調節持股水位，防守優先。"
    return format_card(
        title=f"大盤風控制度與部位曝險指南 ({m_name})",
        pre_content="\n".join(card_lines),
        emoji="🛡️",
        footer=footer,
    )


# ==========================================
# 2. Resonance Stock Picks (多維共振選股)
# ==========================================

def fetch_resonance_picks(index_name: str = "台灣50", limit: int = 12) -> List[Dict[str, Any]]:
    """Fetch multi-model resonance stock recommendations."""
    cache_key = f"resonance:{index_name}:{limit}"
    cached = _resonance_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/predictions/resonance", params={"index_name": index_name, "limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _resonance_cache.set(cache_key, items)
            return items
        stale = _resonance_cache.get_stale(cache_key)
        if stale:
            logger.info(f"StockData resonance API unavailable; serving stale cache for {index_name}")
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_resonance_markdown(picks: List[Dict[str, Any]], title: str = "") -> str:
    """Format resonance picks into clean Telegram HTML card with pre code block."""
    if not picks:
        return format_card("多模型交集共振焦點選股推薦", "目前市場暫無觸發共振門檻之焦點標的，建議觀望或查看大盤風控。", emoji="👑")

    clean_title = re.sub(r"[\*【】]", "", title).strip() if title else "多模型交集共振選股推薦"
    clean_title = re.sub(r"^[👑\s]+", "", clean_title)

    blocks = []
    for i, p in enumerate(picks[:10], 1):
        if not isinstance(p, dict):
            continue
        ticker = p.get("ticker") or "未知"
        name = p.get("name") or ""
        t_display = f"{ticker} {name}".strip()
        price = p.get("current_price") or 0.0
        target = p.get("predicted_price") or 0.0
        potential = p.get("potential") or 0.0
        model = p.get("model_name") or "Quant"
        strategy = p.get("strategy_type") or ""
        pe = p.get("pe")
        t_net = p.get("trust_net_5d") or 0
        f_net = p.get("foreign_net_5d") or 0

        badges = []
        if "玄鐵" in strategy:
            badges.append("玄鐵")
        if "TimesFM" in model:
            badges.append("TimesFM")
        elif "LSTM" in model:
            badges.append("LSTM")
        if t_net and t_net > 0:
            badges.append(f"投信+{t_net}")
        if f_net and f_net > 0:
            badges.append(f"外資+{f_net}")

        badge_str = f" [{'|'.join(badges)}]" if badges else ""
        sign = "+" if potential >= 0 else ""

        entry_lines = [
            f"[{i}] {t_display}{badge_str}",
            f"現價: {price:,.1f} ➔ 預期: {target:,.1f} ({sign}{potential:.1f}%)"
        ]
        extra = []
        if pe is not None:
            extra.append(f"PE: {float(pe):.1f}x")
        if p.get("risk_reward_ratio") is not None:
            extra.append(f"盈虧比: {float(p['risk_reward_ratio']):.2f}")
        if extra:
            entry_lines.append(" | ".join(extra))
        blocks.append("\n".join(entry_lines))

    pre_content = "\n\n".join(blocks) if blocks else "無有效共振標的資料"
    footer = "多重模型交集訊號；進場前請先以 /macro 確認整體部位曝險。"
    return format_card(
        title=clean_title,
        pre_content=pre_content,
        emoji="👑",
        footer=footer,
    )


# ==========================================
# 3. Google TimesFM 5-Day Forecast (時序大模型)
# ==========================================

TIMESFM_TIMESTAMP_FIELDS = (
    "timestamp",
    "analysis_date",
    "data_as_of",
    "prediction_date",
    "created_at",
    "updated_at",
    "date",
)


def _timesfm_timestamp_key(item: Dict[str, Any]) -> tuple:
    """Return a comparable UTC key for ISO, Unix-second, or Unix-millisecond dates."""
    raw_value = next(
        (
            item.get(field)
            for field in TIMESFM_TIMESTAMP_FIELDS
            if item.get(field) is not None and str(item.get(field)).strip()
        ),
        None,
    )
    if raw_value is None:
        return (0, 0.0, "")

    try:
        numeric_value = float(raw_value)
        if math.isfinite(numeric_value):
            if abs(numeric_value) >= 100_000_000_000:
                numeric_value /= 1000.0
            return (2, numeric_value, "")
    except (TypeError, ValueError):
        pass

    text_value = str(raw_value).strip()
    try:
        # Slash-delimited dates are intentionally interpreted as YYYY/MM/DD;
        # other locale orders fall back safely instead of being guessed.
        normalized_text = text_value.replace("/", "-")
        iso_value = normalized_text[:-1] + "+00:00" if normalized_text.endswith("Z") else normalized_text
        parsed = datetime.fromisoformat(iso_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (2, parsed.timestamp(), "")
    except ValueError:
        return (1, 0.0, text_value)

def fetch_timesfm_predictions(
    action: str = "bullish",
    limit: int = 10,
    ticker: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch TimesFM leaderboard data or the latest prediction for one ticker."""
    is_bearish = "bear" in action.lower() or "跌" in action
    clean_ticker = ticker.strip().upper() if ticker else ""
    if clean_ticker:
        ep = f"/api/v1/predictions/history/{quote(clean_ticker, safe='')}"
    else:
        ep = "/api/v1/predictions/timesfm/top-bearish" if is_bearish else "/api/v1/predictions/timesfm/top-bullish"
    cache_key = f"timesfm:{action}:{limit}:{clean_ticker}"
    cached = _timesfm_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json(ep, params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            if clean_ticker:
                items = [
                    item for item in items
                    if str(item.get("ticker", "")).upper() == clean_ticker
                    and str(item.get("model_name", "")).lower() == "timesfm"
                ]
                # History responses may contain multiple runs; show newest TimesFM first.
                items.sort(key=_timesfm_timestamp_key, reverse=True)
            _timesfm_cache.set(cache_key, items)
            return items
        stale = _timesfm_cache.get_stale(cache_key)
        if stale:
            logger.info(f"StockData timesfm API unavailable; serving stale cache for {clean_ticker or action}")
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_timesfm_markdown(items: List[Dict[str, Any]], is_bearish: bool = False) -> str:
    """Format TimesFM predictions into clean Telegram HTML card with pre code block."""
    title = "Google TimesFM 5日看跌避險榜" if is_bearish else "Google TimesFM 5日時序大模型看漲榜"
    if not items:
        return format_card(title, "查無相關預測數據。", emoji="🧠")

    blocks = []
    for i, p in enumerate(items[:10], 1):
        if not isinstance(p, dict):
            continue
        ticker = p.get("ticker") or "未知"
        name = p.get("name") or ""
        t_display = f"{ticker} {name}".strip()
        price = p.get("current_price") or 0.0
        target = p.get("predicted_price") or 0.0
        potential = p.get("potential") or 0.0
        rr = p.get("risk_reward_ratio")

        sign = "+" if potential >= 0 else ""
        entry_lines = [
            f"[{i}] {t_display}",
            f"現價: {price:,.1f} ➔ 5日目標: {target:,.1f} ({sign}{potential:.1f}%)"
        ]
        info = []
        if rr is not None:
            info.append(f"盈虧比: {float(rr):.2f}")
        if p.get("pe") is not None:
            info.append(f"PE: {float(p['pe']):.1f}x")
        if info:
            entry_lines.append(" | ".join(info))
        blocks.append("\n".join(entry_lines))

    pre_content = "\n\n".join(blocks) if blocks else "查無有效預測數據。"
    footer = "Google Research 500M 基礎模型；盈虧比 RR >= 1.5 具統計顯著性。"
    return format_card(
        title=title,
        pre_content=pre_content,
        emoji="🧠",
        footer=footer,
    )


# ==========================================
# 4. Xuantie Heavy Sword Pullback (玄鐵重劍)
# ==========================================

def fetch_xuantie_pullbacks(index_name: str = "台灣50", limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch Xuantie Heavy Sword MA60/120 pullback swing trading signals."""
    cache_key = f"xuantie:{index_name}:{limit}"
    cached = _xuantie_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/predictions/xuantie", params={"index_name": index_name, "limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _xuantie_cache.set(cache_key, items)
            return items
        stale = _xuantie_cache.get_stale(cache_key)
        if stale:
            logger.info(f"StockData xuantie API unavailable; serving stale cache for {index_name}")
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_xuantie_markdown(items: List[Dict[str, Any]]) -> str:
    """Format Xuantie pullbacks into clean Telegram HTML card with pre code block."""
    if not items:
        return format_card("玄鐵重劍：MA60/120 均線波段回踩買點", "目前市場無回踩季線/半年線支撐之標的。", emoji="🗡️")

    blocks = []
    for i, p in enumerate(items[:10], 1):
        if not isinstance(p, dict):
            continue
        ticker = p.get("ticker") or "未知"
        name = p.get("name") or ""
        t_display = f"{ticker} {name}".strip()
        price = p.get("current_price") or 0.0
        target = p.get("predicted_price") or 0.0
        potential = p.get("potential") or 0.0
        pullback_type = p.get("pullback_type") or "季線/半年線支撐"
        ma60 = p.get("ma60")
        ma120 = p.get("ma120")

        sign = "+" if potential >= 0 else ""
        entry_lines = [
            f"[{i}] {t_display} ({pullback_type})",
            f"現價: {price:,.1f} ➔ 預期: {target:,.1f} ({sign}{potential:.1f}%)"
        ]
        ma_info = []
        if ma60 is not None:
            ma_info.append(f"MA60: {float(ma60):.1f}")
        if ma120 is not None:
            ma_info.append(f"MA120: {float(ma120):.1f}")
        if ma_info:
            entry_lines.append(" | ".join(ma_info))
        blocks.append("\n".join(entry_lines))

    pre_content = "\n\n".join(blocks) if blocks else "目前無有效回踩標的。"
    footer = "重劍無鋒，大巧不工。順大勢逆小勢，專注強支撐低吸。"
    return format_card(
        title="玄鐵重劍：MA60/120 均線波段回踩買點",
        pre_content=pre_content,
        emoji="🗡️",
        footer=footer,
    )


# ==========================================
# 5. Key Broker Branches (券商關鍵主力分點)
# ==========================================

def fetch_broker_summary(ticker: str, days: int = 20) -> Dict[str, Any]:
    """Fetch top broker branches buying and selling for a specific stock."""
    clean_ticker = ticker.strip().upper()
    if not clean_ticker.endswith(".TW") and not clean_ticker.endswith(".TWO") and clean_ticker.isdigit():
        clean_ticker += ".TW"

    cache_key = f"broker:{clean_ticker}:{days}"
    cached = _broker_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json(f"/api/v1/market/broker/summary/{clean_ticker}", params={"days": days})
        if res and isinstance(res, dict) and "top_buyers" in res:
            _broker_cache.set(cache_key, res)
            return res
        stale = _broker_cache.get_stale(cache_key)
        if stale:
            logger.info(f"StockData broker API unavailable; serving stale cache for {clean_ticker}")
            return stale
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_broker_summary_markdown(data: Dict[str, Any]) -> str:
    """Format broker summary into clean Telegram HTML card with pre code block."""
    if not data or "top_buyers" not in data:
        return "🏢 <b>券商關鍵主力分點進出</b>\n\n查無該標的近期的券商分點買賣資料（僅支援台股上市公司，如 2330.TW）。"

    ticker = data.get("ticker", "")
    days = data.get("days", 20)
    start_d = data.get("start_date", "")
    end_d = data.get("end_date", "")

    buyers = data.get("top_buyers", [])
    sellers = data.get("top_sellers", [])

    card_lines = [
        f"統計區間: {start_d} ~ {end_d}",
        "",
        "[主力買超分點 Top 5]"
    ]
    for i, b in enumerate(buyers[:5], 1):
        b_name = b.get("broker_name", "未知分點")
        net = int(round(b.get("total_net") or 0))
        buy = int(round(b.get("total_buy") or 0))
        sell = int(round(b.get("total_sell") or 0))
        sign = "+" if net > 0 else ""
        card_lines.append(f"{i}. {b_name} {sign}{net:,}張 (買{buy:,}|賣{sell:,})")

    card_lines.append("")
    card_lines.append("[主力賣超分點 Top 5]")
    for i, s in enumerate(sellers[:5], 1):
        s_name = s.get("broker_name", "未知分點")
        net = int(round(s.get("total_net") or 0))
        buy = int(round(s.get("total_buy") or 0))
        sell = int(round(s.get("total_sell") or 0))
        card_lines.append(f"{i}. {s_name} {net:,}張 (買{buy:,}|賣{sell:,})")

    footer = "外資多經外資券商下單；本土主力常盤踞於地緣或特選券商分點。"
    return format_card(
        title=f"{ticker} 近 {days} 日券商主力關鍵分點排行",
        pre_content="\n".join(card_lines),
        emoji="🏢",
        footer=footer,
    )


# ==========================================
# 6. Structural Calendars & Macro Catalysts
# ==========================================

CALENDAR_CATEGORY_ALIASES = {
    "all": "all",
    "earn": "earn",
    "earnings": "earn",
    "call": "earn",
    "calls": "earn",
    "econ": "econ",
    "economic": "econ",
    "macro": "econ",
    "fed": "fed",
    "rate": "fed",
    "rates": "fed",
    "comm": "comm",
    "commodity": "comm",
    "commodities": "comm",
    "tw": "tw",
    "taiwan": "tw",
    "us": "us",
    "usa": "us",
}


def normalize_calendar_category(category: str = "all") -> str:
    """Normalize documented calendar aliases to the API fetch categories."""
    return CALENDAR_CATEGORY_ALIASES.get(str(category).strip().lower(), "all")


def fetch_calendar_data(category: str = "all") -> Dict[str, Any]:
    """Fetch structural investing calendars (earnings calls, economics, fed-rate, commodities)."""
    norm_cat = normalize_calendar_category(category)
    cache_key = f"cal:{norm_cat}"
    cached = _calendar_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        result = {}

        # 1. Fast macro summary for fed-rate and commodities (avoids individual scrape timeout)
        if norm_cat in ("all", "fed", "comm"):
            summary_res = _get_json("/api/v1/macro/investing/summary")
            if summary_res and summary_res.get("success"):
                s_data = summary_res.get("data", {})
                if norm_cat in ("all", "fed") and s_data.get("fed_rate"):
                    result["fed"] = s_data["fed_rate"]
                if norm_cat in ("all", "comm") and s_data.get("commodities"):
                    result["commodities"] = s_data["commodities"]

        # Fallback to direct fed-rate if summary didn't include it
        if norm_cat in ("all", "fed") and "fed" not in result:
            fed_data = _get_json("/api/v1/macro/investing/fed-rate")
            if fed_data and fed_data.get("success") and fed_data.get("data"):
                result["fed"] = fed_data.get("data", {})

        # Fallback to direct commodities
        if norm_cat in ("all", "comm") and "commodities" not in result:
            comm_data = _get_json("/api/v1/macro/investing/commodities")
            if comm_data and comm_data.get("success") and comm_data.get("data"):
                result["commodities"] = comm_data.get("data", {})

        # 2. Upcoming Corporate Earnings Calls (法說會與重磅財報跨市場行事曆)
        if norm_cat in ("all", "earn", "tw", "us"):
            market_param = "TW" if norm_cat == "tw" else ("US" if norm_cat == "us" else "ALL")
            ec_res = _get_json("/api/v1/earnings-call/upcoming", params={"market": market_param, "time_filter": "UPCOMING", "limit": 15})
            calls = (ec_res.get("data") if ec_res and ec_res.get("success") else None)
            if not calls:
                ec_all = _get_json("/api/v1/earnings-call/upcoming", params={"market": market_param, "days": 14, "limit": 15})
                if ec_all and ec_all.get("success"):
                    calls = ec_all.get("data")
            if calls:
                result["earnings_calls"] = calls
            else:
                # Fallback to legacy earnings calendar if earnings-call was empty
                earn_data = _get_json("/api/v1/macro/investing/earnings-calendar")
                if earn_data and earn_data.get("success") and earn_data.get("data"):
                    result["earnings"] = earn_data.get("data", [])

        # 3. Global Economic Indicators Calendar
        if norm_cat in ("all", "econ"):
            econ_data = _get_json("/api/v1/macro/investing/economic-calendar")
            if econ_data and econ_data.get("success") and econ_data.get("data"):
                result["economic"] = econ_data.get("data", [])

        if result:
            _calendar_cache.set(cache_key, result)
            return result
        stale = _calendar_cache.get_stale(cache_key)
        if stale:
            logger.info(f"StockData calendar API unavailable; serving stale cache for {norm_cat}")
            return stale
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_calendar_markdown(data: Dict[str, Any], cat: str = "all") -> str:
    """Format calendar and catalyst data into clean Telegram HTML card with pre code block."""
    if not data or not isinstance(data, dict):
        return format_card("全球市場總經與美股日曆", "無行事曆資料", emoji="📅")

    card_lines = []

    # 1. 法人說明會與重磅財報 (優先展示跨市場法說會：台股/美股/日股/韓股)
    calls = data.get("earnings_calls")
    earns = data.get("earnings")

    if calls and isinstance(calls, list) and len(calls) > 0:
        card_lines.append("[全球跨市場法說會暨財報日程]")
        for c in calls[:6]:
            if isinstance(c, dict):
                mkt = c.get("market", "")
                ticker = c.get("ticker", "")
                name = c.get("name", "")
                dt = c.get("call_date", "")
                dt_short = "/".join(dt.split("-")[1:]) if "-" in dt else dt
                t_str = c.get("call_time", "")
                cd = c.get("countdown_days")
                status = c.get("status", "")
                tag = " (今日)" if cd == 0 or status == "today" else (" (明日)" if cd == 1 else (f" (倒數{cd}天)" if cd and cd > 1 else ""))
                card_lines.append(f"• [{mkt}] {ticker} {name}: {dt_short} {t_str}{tag}")
        card_lines.append("")

    if earns and isinstance(earns, list) and len(earns) > 0:
        card_lines.append("[美股重磅企業財報]")
        for e in earns[:5]:
            if isinstance(e, dict):
                t = e.get("ticker", "")
                name = e.get("name", "")
                d = e.get("date", "")
                eps = e.get("eps_forecast", "N/A")
                card_lines.append(f"• {t} {name}: {d} (預估EPS: {eps})")
        card_lines.append("")

    # 2. 全球重大總經指標
    econs = data.get("economic")
    if econs and isinstance(econs, list) and len(econs) > 0:
        card_lines.append("[全球重要總經指標公布]")
        for ec in econs[:5]:
            if isinstance(ec, dict):
                country = ec.get("country", "")
                time_str = ec.get("time", "")
                ev = ec.get("event", "")
                card_lines.append(f"• [{country}] {time_str} {ev}")
        card_lines.append("")

    # 3. CME 聯準會利率路徑
    fed = data.get("fed")
    if isinstance(fed, dict) and fed:
        probs = fed.get("probabilities") or fed.get("target_rates") or []
        if isinstance(probs, list) and len(probs) > 0:
            card_lines.append("[CME 聯準會利率路徑]")
            meeting = fed.get("meeting_date", "近期")
            upd = fed.get("updated_at", "")
            card_lines.append(f"下次會議: {meeting}" + (f" (更新: {upd})" if upd else ""))
            for p in probs[:3]:
                if isinstance(p, dict):
                    rate = p.get("rate_range", "")
                    prob = p.get("probability") or p.get("current_probability") or p.get("probability_value", "")
                    card_lines.append(f"• 區間 {rate}: {prob}")
            card_lines.append("")

    # 4. 大宗商品週期行情 (防禦 +, - 與 % 重複符號)
    comm = data.get("commodities")
    if isinstance(comm, dict) and comm:
        card_lines.append("[大宗商品週期行情]")
        for k, v in comm.items():
            if isinstance(v, dict):
                c_name = v.get("name", k)
                d_chg = str(v.get("daily_change", "0")).strip().rstrip("%")
                if not d_chg.startswith(("+", "-")):
                    d_chg = f"+{d_chg}"
                ind = f" ({v.get('indicator', '')})" if v.get("indicator") else ""
                card_lines.append(f"• {c_name}: 日漲跌 {d_chg}%{ind}")
        card_lines.append("")

    if not card_lines:
        card_lines.append("暫無近期行事曆或總經催化劑資料。")

    footer = "前瞻日曆由 stockdata.david888.com 實時自動同步。"
    return format_card(
        title="全球總經與美股重磅行事曆",
        pre_content="\n".join(card_lines).strip(),
        emoji="📅",
        footer=footer,
    )


# ==========================================
# 7. LangChain Tool Definitions
# ==========================================

@tool
def get_macro_regime_analysis(market: str = "tw") -> Dict[str, Any]:
    """
    Analyzes overall stock market risk regime, S&P 500 / TWII moving average health, VIX, and recommended portfolio exposure percentage (0% to 100%).
    ALWAYS call this tool when users ask:
    - '現在大盤風險如何？'
    - '目前適合買股票嗎？建議幾成部位？'
    - '台股/美股多空體質與風控曝險評估'
    """
    logger.info(f"=== [Tool] get_macro_regime_analysis called for: {market} ===")
    data = fetch_macro_regime(market)
    summary = format_macro_regime_markdown(data)
    return {
        "market": market,
        "exposure": data.get("exposure", 0.0),
        "regime_name": data.get("regime_name", ""),
        "vix": data.get("vix", 0.0),
        "warnings": data.get("warnings", []),
        "formatted_summary": summary
    }


@tool
def get_resonance_picks(index_name: str = "台灣50", limit: int = 8) -> Dict[str, Any]:
    """
    Finds high-probability stock recommendations from the Multi-Model Resonance Hierarchy:
    - Quadruple Resonance: Xuantie MA Pullback ∩ Institutional Accumulation ∩ LSTM Bullish ∩ TimesFM Bullish.
    - Triple Resonance: Technical Support ∩ Institutional Buying ∩ ML Bullish ∩ Reasonable Valuation (P/E < 25).
    - Double ML Resonance: LSTM & TimesFM simultaneous bullish agreement.
    ALWAYS call this tool when users ask:
    - '今天有推薦什麼股票？'
    - '有哪些多重共振強勢標的？'
    - '推薦符合技術面與籌碼面的股票'
    """
    logger.info(f"=== [Tool] get_resonance_picks called for: {index_name} ===")
    picks = fetch_resonance_picks(index_name, limit)
    summary = format_resonance_markdown(picks)
    return {
        "index_name": index_name,
        "count": len(picks),
        "picks": picks,
        "formatted_summary": summary
    }


@tool
def get_timesfm_predictions_tool(ticker_or_type: str = "bullish", limit: int = 8) -> Dict[str, Any]:
    """
    Fetches Google Research TimesFM 2.5 500M foundational time-series model 5-day stock forecasts and Risk/Reward Ratios (RR >= 1.5).
    Provides P10 downside defensive stops, P50 median targets, and P90 upside profit targets.
    Use when users ask:
    - 'TimesFM 大模型預測排行榜'
    - '用 Google 時序大模型預測股票走勢與盈虧比'
    - '有哪些高勝率與高盈虧比的股票？'
    """
    logger.info(f"=== [Tool] get_timesfm_predictions_tool called for: {ticker_or_type} ===")
    raw_arg = ticker_or_type.strip()
    is_bear = "bear" in raw_arg.lower() or "跌" in raw_arg
    is_mode = raw_arg.lower() in {"", "bullish", "bearish", "top", "看漲", "看跌", "避險"}
    ticker = None if is_mode or is_bear else raw_arg
    items = fetch_timesfm_predictions("bearish" if is_bear else "bullish", limit, ticker)
    summary = format_timesfm_markdown(items, is_bearish=is_bear)
    return {
        "type": "bearish" if is_bear else "bullish",
        "count": len(items),
        "predictions": items,
        "formatted_summary": summary
    }


@tool
def get_xuantie_pullback_picks(index_name: str = "台灣50", limit: int = 8) -> Dict[str, Any]:
    """
    Fetches Xuantie Heavy Sword trend-pullback swing trading opportunities (MA60 > MA120 upward trend + price pulling back to MA60/120 support ±3%).
    Use when users ask:
    - '玄鐵重劍策略推薦股票'
    - '回踩季線或半年線支撐的波段買點'
    - '拉回低吸起漲股推薦'
    """
    logger.info(f"=== [Tool] get_xuantie_pullback_picks called for: {index_name} ===")
    items = fetch_xuantie_pullbacks(index_name, limit)
    summary = format_xuantie_markdown(items)
    return {
        "index_name": index_name,
        "count": len(items),
        "picks": items,
        "formatted_summary": summary
    }


@tool
def get_broker_branch_trades(ticker: str, days: int = 20) -> Dict[str, Any]:
    """
    Fetches the top 10 buyer and seller broker branches (如港商麥格理、美商高盛、富邦、國泰等分點明細) and accumulated shares for a Taiwan stock.
    Use when users ask:
    - '台積電 2330 最近有哪些券商主力分點在買？'
    - '查詢特定股票的關鍵券商營業部進出明細'
    - '主力分點籌碼集中度'
    """
    logger.info(f"=== [Tool] get_broker_branch_trades called for: {ticker} (days: {days}) ===")
    data = fetch_broker_summary(ticker, days)
    summary = format_broker_summary_markdown(data)
    return {
        "ticker": ticker,
        "days": days,
        "data": data,
        "formatted_summary": summary
    }


@tool
def get_market_investing_calendars(category: str = "all") -> Dict[str, Any]:
    """
    Fetches forward-looking investing calendars:
    - US Major Corporate Earnings calendar (ORCL, ADBE, etc.)
    - Global Macroeconomic events calendar (CPI, Non-Farm Payrolls, PMI)
    - CME FedWatch official interest rate probabilities
    - Global commodities cyclical updates (Gold, Crude Oil, Copper)
    Use when users ask:
    - '本週有哪些重要美股財報？'
    - '近期有什麼重大總經數據要公布？'
    - '查詢 CME FedWatch 利率決策機率'
    - '黃金與原油等大宗商品走勢'
    """
    logger.info(f"=== [Tool] get_market_investing_calendars called for: {category} ===")
    normalized_category = normalize_calendar_category(category)
    data = fetch_calendar_data(normalized_category)
    summary = format_calendar_markdown(data, cat=normalized_category)
    return {
        "category": category,
        "data": data,
        "formatted_summary": summary
    }


# ==========================================
# 8. Advanced Quant Tools (Timestral, MOIRAI-2, Screener, Alignment, Earnings Calls, Network, Clef, Sessions)
# ==========================================

_timestral_cache = TTLCache(default_ttl=600.0, max_size=100)
_moirai_cache = TTLCache(default_ttl=600.0, max_size=100)
_screen_cache = TTLCache(default_ttl=600.0, max_size=50)
_alignment_cache = TTLCache(default_ttl=600.0, max_size=100)
_earnings_call_cache = TTLCache(default_ttl=900.0, max_size=100)
_company_network_cache = TTLCache(default_ttl=3600.0, max_size=100)
_clef_cache = TTLCache(default_ttl=600.0, max_size=100)
_sessions_cache = TTLCache(default_ttl=120.0, max_size=10)


def _normalize_quant_ticker(ticker: str) -> str:
    """Normalize numeric stock code (e.g. '2330') to Taiwan ticker ('2330.TW')."""
    clean = ticker.strip().upper()
    if clean.isdigit() and not clean.endswith(".TW") and not clean.endswith(".TWO"):
        return f"{clean}.TW"
    return clean


def fetch_timestral_predictions(action: str = "bullish", limit: int = 8, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch Mistral Timestral-209M predictions."""
    is_bearish = "bear" in action.lower() or "跌" in action
    clean_ticker = ticker.strip().upper() if ticker else ""
    if clean_ticker:
        ep = f"/api/v1/predictions/history/{quote(clean_ticker, safe='')}"
    else:
        ep = "/api/v1/predictions/timestral/top-bearish" if is_bearish else "/api/v1/predictions/timestral/top-bullish"
    cache_key = f"timestral:{action}:{limit}:{clean_ticker}"
    cached = _timestral_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json(ep, params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            if clean_ticker and isinstance(items, list):
                items = sorted(items, key=_timesfm_timestamp_key, reverse=True)
            _timestral_cache.set(cache_key, items)
            return items
        return _timestral_cache.get_stale(cache_key) or []

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_moirai_predictions(limit: int = 8) -> List[Dict[str, Any]]:
    """Fetch Salesforce MOIRAI-2 predictions."""
    cache_key = f"moirai:{limit}"
    cached = _moirai_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/predictions/moirai/top-bullish", params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _moirai_cache.set(cache_key, items)
            return items
        return _moirai_cache.get_stale(cache_key) or []

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_quant_screen(
    direction: str = "bullish",
    models: Optional[str] = None,
    pe_range: Optional[str] = None,
    min_potential: Optional[float] = None,
    risk_reward: Optional[float] = None,
    ma60: Optional[str] = None,
    institutional: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Execute multi-factor quant screener."""
    params: Dict[str, Any] = {"direction": direction, "limit": limit}
    if models:
        params["models"] = models
    if pe_range:
        params["pe_range"] = pe_range
    if min_potential is not None:
        params["min_potential"] = min_potential
    if risk_reward is not None:
        params["risk_reward"] = risk_reward
    if ma60:
        params["ma60"] = ma60
    if institutional:
        params["institutional"] = institutional

    cache_key = f"screen:{json.dumps(params, sort_keys=True)}"
    cached = _screen_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/predictions/screen", params=params)
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _screen_cache.set(cache_key, items)
            return items
        return _screen_cache.get_stale(cache_key) or []

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_signal_alignment(ticker: str) -> Dict[str, Any]:
    """Fetch multi-source signal alignment card for a ticker."""
    clean_ticker = _normalize_quant_ticker(ticker)
    cache_key = f"alignment:{clean_ticker}"
    cached = _alignment_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json(f"/api/v1/predictions/alignment/{quote(clean_ticker, safe='')}")
        if res and isinstance(res, dict) and "ticker" in res:
            _alignment_cache.set(cache_key, res)
            return res
        return _alignment_cache.get_stale(cache_key) or {}

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_upcoming_earnings_calls(market: str = "ALL", limit: int = 10) -> Dict[str, Any]:
    """Fetch upcoming cross-market corporate earnings calls."""
    cache_key = f"ec_upcoming:{market}:{limit}"
    cached = _earnings_call_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/earnings-call/upcoming", params={"market": market.upper(), "limit": limit})
        if res and res.get("success"):
            _earnings_call_cache.set(cache_key, res)
            return res
        return _earnings_call_cache.get_stale(cache_key) or {}

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_ticker_earnings_calls(ticker: str) -> Dict[str, Any]:
    """Fetch earnings call history and upcoming guidance for a specific ticker."""
    clean_ticker = _normalize_quant_ticker(ticker)
    cache_key = f"ec_ticker:{clean_ticker}"
    cached = _earnings_call_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json(f"/api/v1/earnings-call/{quote(clean_ticker, safe='')}")
        if res and res.get("success"):
            _earnings_call_cache.set(cache_key, res)
            return res
        return _earnings_call_cache.get_stale(cache_key) or {}

    return _sd_singleflight.run(cache_key, _fetch)


def _is_invalid_network_url(url: Any) -> bool:
    """Check if a company network URL is missing, invalid, or contaminated with placeholder test data."""
    if not url or not isinstance(url, str):
        return True
    u_str = url.strip()
    if not u_str:
        return True
    try:
        parsed = urlparse(u_str)
        if not parsed.scheme or not parsed.netloc:
            return True
        qs = parse_qs(parsed.query, keep_blank_values=True)
        netloc_lower = parsed.netloc.lower()
        path_lower = parsed.path.lower()
        is_graph_endpoint = "taiwan-company-network" in netloc_lower or "/graph" in path_lower

        company_vals = qs.get("company", [])
        if is_graph_endpoint and not company_vals:
            return True
        for v_item in company_vals:
            val = str(v_item).strip().lower()
            if not val or val in ("test", "undefined", "none", "null", "empty"):
                return True
    except Exception:
        return True
    return False


def _is_invalid_image_url(url: Any) -> bool:
    """Check if an image URL is invalid, empty, or points to placeholder test assets."""
    if not url or not isinstance(url, str):
        return True
    u_str = url.strip()
    if not u_str:
        return True
    try:
        parsed = urlparse(u_str)
        if not parsed.scheme or not parsed.netloc:
            return True
        path_parts = [p.lower() for p in parsed.path.split("/") if p]
        test_stem_re = re.compile(r"^test([_-]?(sub|img|pic|image|thumb|icon|logo|dummy)?\d*|\d+)$", re.IGNORECASE)
        for part in path_parts:
            stem = part.rsplit(".", 1)[0]
            if stem in ("test", "undefined", "null", "placeholder", "demo", "mock", "sample"):
                return True
            if test_stem_re.match(stem):
                return True
        qs = parse_qs(parsed.query, keep_blank_values=True)
        for k, vlist in qs.items():
            for v in vlist:
                v_clean = str(v).strip().lower()
                if v_clean in ("test", "undefined", "null", "mock") or test_stem_re.match(v_clean):
                    return True
    except Exception:
        return True
    return False


def _sanitize_company_network_payload(data: Any, ticker: Any = "") -> Dict[str, Any]:
    """Sanitize company network API payload to defend against 'company=test' pollution.

    - Reconstructs valid 'web_url' using data['name'] or ticker if URL is missing or tainted.
    - Cleans 'image_url' if contaminated with test placeholders.
    - Sanitizes sub-URLs inside 'relationships' structure.
    - Returns a deep-copied sanitized dict to prevent in-place cache mutation.
    """
    if not isinstance(data, dict):
        return {}

    data = copy.deepcopy(data)

    # 1. Determine canonical company name or ticker identifier safely
    candidate_name = data.get("name") or data.get("company_name") or data.get("company")
    cand_str = str(candidate_name).strip() if candidate_name is not None else ""
    if cand_str.lower() in ("test", "undefined", "none", "null", "company", ""):
        cand_str = ""

    # Strip the more specific .TWO before .TW to avoid leaves like '6488O'
    clean_ticker = str(ticker).strip().upper().replace(".TWO", "").replace(".TW", "") if ticker is not None and str(ticker).strip() else ""
    if clean_ticker.lower() in ("test", "undefined", "none", "null", ""):
        clean_ticker = ""

    raw_data_ticker = str(data.get("ticker") or "").strip().upper().replace(".TWO", "").replace(".TW", "")
    if raw_data_ticker.lower() in ("test", "undefined", "none", "null", ""):
        raw_data_ticker = ""

    canonical_name = cand_str or clean_ticker or raw_data_ticker
    if canonical_name.lower() in ("test", "undefined", "none", "null", "company", ""):
        canonical_name = ""

    if canonical_name:
        encoded_name = quote(canonical_name, safe="")
        canonical_web_url = f"https://taiwan-company-network.david888.com/graph?company={encoded_name}"
    else:
        canonical_web_url = None

    # 2. Check and sanitize web_url
    current_web_url = data.get("web_url")
    if _is_invalid_network_url(current_web_url):
        data["web_url"] = canonical_web_url

    # 3. Check and sanitize image_url
    image_url = data.get("image_url")
    if image_url is not None:
        if _is_invalid_image_url(image_url):
            data["image_url"] = None

    # 4. Helper for sanitizing relationship items
    def _clean_rel_item(item: Dict[str, Any]) -> None:
        rel_url = item.get("web_url") or item.get("url")
        if rel_url and _is_invalid_network_url(rel_url):
            rel_name = item.get("name") or item.get("company_name") or item.get("target") or item.get("company") or item.get("id") or item.get("code")
            rel_str = str(rel_name).strip() if rel_name is not None else ""
            if rel_str and rel_str.lower() not in ("test", "undefined", "none", "null", "company", ""):
                corr_url = f"https://taiwan-company-network.david888.com/graph?company={quote(rel_str, safe='')}"
                if "web_url" in item:
                    item["web_url"] = corr_url
                if "url" in item:
                    item["url"] = corr_url
            else:
                if "web_url" in item:
                    item["web_url"] = None
                if "url" in item:
                    item["url"] = None
        rel_img = item.get("image_url")
        if rel_img is not None:
            if _is_invalid_image_url(rel_img):
                item["image_url"] = None

    # 5. Check and sanitize relationships (both list and dict formats, e.g. upstream/downstream/nodes/links)
    relationships = data.get("relationships")
    if isinstance(relationships, list):
        for item in relationships:
            if isinstance(item, dict):
                _clean_rel_item(item)
    elif isinstance(relationships, dict):
        for key, sub_items in relationships.items():
            if isinstance(sub_items, list):
                for item in sub_items:
                    if isinstance(item, dict):
                        _clean_rel_item(item)

    # 6. Check root-level upstream/downstream lists if present
    for root_rel_key in ("upstream", "downstream"):
        root_items = data.get(root_rel_key)
        if isinstance(root_items, list):
            for item in root_items:
                if isinstance(item, dict):
                    _clean_rel_item(item)

    return data


def fetch_company_network(ticker: str) -> Dict[str, Any]:
    """Fetch Taiwan Company Network structure and subsidiaries."""
    clean_code = ticker.strip().upper().replace(".TW", "").replace(".TWO", "")
    cache_key = f"network:{clean_code}"
    cached = _company_network_cache.get(cache_key)
    if cached is not None:
        return _sanitize_company_network_payload(cached, ticker)

    def _fetch():
        res = _get_json(f"/api/v1/market/company-network/{quote(clean_code, safe='')}")
        if not res or not res.get("success"):
            res = _get_json("/api/v1/market/company-network", params={"ticker": clean_code})
        if res and res.get("success") and "data" in res:
            d = res["data"]
            if isinstance(d, dict):
                d = _sanitize_company_network_payload(d, ticker)
            _company_network_cache.set(cache_key, d)
            return d
        stale = _company_network_cache.get_stale(cache_key)
        if stale:
            return _sanitize_company_network_payload(stale, ticker)
        return {}

    raw = _sd_singleflight.run(cache_key, _fetch)
    if isinstance(raw, dict) and raw:
        return _sanitize_company_network_payload(raw, ticker)
    return _sanitize_company_network_payload({}, ticker)


def fetch_clef_stock_verdict(ticker: str) -> Dict[str, Any]:
    """Fetch Clef System One Decision Engine verdict."""
    clean_ticker = _normalize_quant_ticker(ticker)
    cache_key = f"clef:{clean_ticker}"
    cached = _clef_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        # Try direct GET endpoint first
        res = _get_json(f"/api/v1/decision/stock/{quote(clean_ticker, safe='')}")
        if res and res.get("success"):
            _clef_cache.set(cache_key, res)
            return res

        # Fallback to POST /api/v1/decision/evaluate
        url = f"{STOCKDATA_BASE_URL.rstrip('/')}/api/v1/decision/evaluate"
        headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
        try:
            resp = requests.post(url, json={"ticker": clean_ticker}, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                d = resp.json()
                _clef_cache.set(cache_key, d)
                return d
        except Exception as e:
            logger.error(f"StockData Clef evaluate error for {clean_ticker}: {e}")
        return _clef_cache.get_stale(cache_key) or {}

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_market_sessions() -> Dict[str, Any]:
    """Fetch live real-time trading sessions across TW, JP, and US."""
    cache_key = "market_sessions"
    cached = _sessions_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/market/calendar/sessions")
        if res and res.get("success") and "sessions" in res:
            d = res["sessions"]
            _sessions_cache.set(cache_key, d)
            return d
        return _sessions_cache.get_stale(cache_key) or {}

    return _sd_singleflight.run(cache_key, _fetch)


@tool
def get_timestral_predictions_tool(ticker_or_type: str = "bullish", limit: int = 8) -> Dict[str, Any]:
    """
    Fetches Mistral Timestral-209M time-series foundation model 5-day stock forecasts and Monte Carlo risk intervals (P10 downside, P50 median target, P90 upside).
    Use when users ask:
    - 'Timestral 時序大模型預測'
    - '查詢 Mistral 209M 大模型看漲或看跌名單'
    - 'Timestral 蒙地卡羅風控區間'
    """
    logger.info(f"=== [Tool] get_timestral_predictions_tool called for: {ticker_or_type} ===")
    raw_arg = ticker_or_type.strip()
    is_bear = "bear" in raw_arg.lower() or "跌" in raw_arg
    is_mode = raw_arg.lower() in {"", "bullish", "bearish", "top", "看漲", "看跌", "避險"}
    ticker = None if is_mode or is_bear else raw_arg
    items = fetch_timestral_predictions("bearish" if is_bear else "bullish", limit, ticker)
    return {
        "model": "Mistral Timestral-209M",
        "direction": "bearish" if is_bear else "bullish",
        "count": len(items),
        "predictions": items
    }


@tool
def get_moirai_predictions_tool(limit: int = 8) -> Dict[str, Any]:
    """
    Fetches Salesforce MOIRAI-2 foundational time-series model 5-day stock forecast rankings and targets.
    Use when users ask:
    - 'MOIRAI-2 時序模型推薦標的'
    - 'Salesforce MOIRAI 大模型看漲清單'
    """
    logger.info(f"=== [Tool] get_moirai_predictions_tool called with limit: {limit} ===")
    items = fetch_moirai_predictions(limit)
    return {
        "model": "Salesforce MOIRAI-2",
        "count": len(items),
        "predictions": items
    }


@tool
def get_quant_screen_picks(
    direction: str = "bullish",
    models: Optional[str] = None,
    pe_range: Optional[str] = None,
    min_potential: Optional[float] = None,
    risk_reward: Optional[float] = None,
    ma60: Optional[str] = None,
    institutional: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Executes a multi-factor quantitative screener across fundamental and technical constraints:
    - direction: 'bullish' (看多) or 'bearish' (看空)
    - models: comma-separated AI models, e.g. 'TimesFM,Timestral,MOIRAI-2'
    - pe_range: e.g. '0-25'
    - min_potential: minimum forecast gain percentage, e.g. 5.0
    - risk_reward: minimum Risk/Reward ratio, e.g. 1.5
    - ma60: moving average support condition ('above', 'pullback', 'breakout')
    - institutional: institutional buying streak ('buying', 'foreign', 'trust', 'both')
    """
    logger.info(f"=== [Tool] get_quant_screen_picks called ===")
    items = fetch_quant_screen(
        direction=direction,
        models=models,
        pe_range=pe_range,
        min_potential=min_potential,
        risk_reward=risk_reward,
        ma60=ma60,
        institutional=institutional,
        limit=limit
    )
    return {
        "count": len(items),
        "picks": items
    }


@tool
def get_signal_alignment_tool(ticker: str) -> Dict[str, Any]:
    """
    Fetches the multi-source Signal Alignment card for a ticker, synthesizing consensus across:
    - Time-Series Foundation Models (TimesFM, Timestral, MOIRAI-2)
    - Taiwan Institutional Chips (Foreign & Trust streaks)
    - Intelligence Sentiment Stance
    - Industry Frontier Discovery Signals
    Use when users ask:
    - '台積電 2330 各模型與籌碼訊號一致度如何？'
    - '多指標共識評估'
    """
    logger.info(f"=== [Tool] get_signal_alignment_tool called for: {ticker} ===")
    data = fetch_signal_alignment(ticker)
    return {
        "ticker": ticker,
        "alignment_data": data
    }


@tool
def get_upcoming_earnings_calls_tool(market: str = "ALL", limit: int = 10) -> Dict[str, Any]:
    """
    Fetches upcoming corporate earnings calls (法人說明會 / 法說會) across Taiwan (TW), US, Japan (JP), and Korea (KR):
    - Dual timezone alignment
    - Days countdown
    - Presentation PDF and audio/video replay links
    Use when users ask:
    - '近期有哪些重量級法說會？'
    - '台股/美股即將召開法說會的清單與簡報'
    """
    logger.info(f"=== [Tool] get_upcoming_earnings_calls_tool called for: {market} ===")
    data = fetch_upcoming_earnings_calls(market, limit)
    return data


@tool
def get_ticker_earnings_calls_tool(ticker: str) -> Dict[str, Any]:
    """
    Fetches historical and upcoming earnings calls, executive guidance (revenue, gross margin, Capex), and slide deck PDF downloads for a specific ticker.
    Use when users ask:
    - '查詢特定公司歷史法說會與最新展望'
    - '下載法說會簡報 PDF'
    """
    logger.info(f"=== [Tool] get_ticker_earnings_calls_tool called for: {ticker} ===")
    data = fetch_ticker_earnings_calls(ticker)
    return data


@tool
def get_company_network_tool(ticker: str) -> Dict[str, Any]:
    """
    Fetches Taiwan Company Network official Ministry of Economic Affairs registration data:
    - Unified Business Number (統一編號 / 統編)
    - Paid-in capital (實收資本額)
    - Chairman / Board representative
    - Upstream holding companies and downstream subsidiaries / investment relations
    - Interactive corporate equity graph URL (web_url)
    Use when users ask:
    - '查詢台積電的統一編號、資本額與董監事'
    - '某公司的集團轉投資與子公司股權關係'
    """
    logger.info(f"=== [Tool] get_company_network_tool called for: {ticker} ===")
    data = fetch_company_network(ticker)
    if not isinstance(data, dict):
        data = {}
    data = _sanitize_company_network_payload(data, ticker)
    web_url = data.get("web_url")
    return {
        "ticker": ticker,
        "web_url": web_url,
        "company_network": data
    }


@tool
def get_clef_stock_verdict_tool(ticker: str) -> Dict[str, Any]:
    """
    Fetches Clef-Flash System One Decision Model verdict:
    - Action probabilities: strong_buy, buy, hold_watch, avoid
    - Conviction score and favorable entry flag
    - Recommendation tag (e.g. 🟢建議佈局, 👀建議觀察, 🔴建議迴避)
    Use when users ask:
    - 'Clef 決策模型對台積電的評分是什麼？'
    - 'System One 勝率與動作機率預測'
    """
    logger.info(f"=== [Tool] get_clef_stock_verdict_tool called for: {ticker} ===")
    data = fetch_clef_stock_verdict(ticker)
    return data


@tool
def get_market_live_sessions_tool() -> Dict[str, Any]:
    """
    Fetches live real-time market trading session states across Taiwan (TWSE), Japan (TSE), and US (NYSE/NASDAQ):
    - Current session (pre_market, regular, lunch_break, after_hours, closed)
    - Seconds to next session transition and countdown
    - Tokyo Stock Exchange lunch break tracking
    Use when users ask:
    - '現在台股/美股/日股開盤了嗎？'
    - '距離開盤/收盤還有多久？'
    - '交易時段查詢'
    """
    logger.info("=== [Tool] get_market_live_sessions_tool called ===")
    data = fetch_market_sessions()
    return {
        "sessions": data
    }


# ==========================================
# 9. Extended Quant Modules (Industry Chain, Tri-Bullish, Discovery, Risk X-Ray, Stock History, Scorecard, Canary, Podcast, Watchlist)
# ==========================================

_industry_chain_cache = TTLCache(default_ttl=900.0, max_size=50)
_tri_bullish_cache = TTLCache(default_ttl=600.0, max_size=50)
_dual_bullish_cache = TTLCache(default_ttl=600.0, max_size=50)
_dual_bearish_cache = TTLCache(default_ttl=600.0, max_size=50)
_discovery_signals_cache = TTLCache(default_ttl=900.0, max_size=50)
_discovery_candidates_cache = TTLCache(default_ttl=900.0, max_size=50)
_risk_xray_cache = TTLCache(default_ttl=300.0, max_size=100)
_stock_history_cache = TTLCache(default_ttl=600.0, max_size=100)
_model_performance_cache = TTLCache(default_ttl=900.0, max_size=50)
_canary_cache = TTLCache(default_ttl=120.0, max_size=10)
_podcast_cache = TTLCache(default_ttl=900.0, max_size=50)
_watchlist_cache = TTLCache(default_ttl=300.0, max_size=50)

THEME_ALIASES: Dict[str, str] = {
    "cpo": "CPO_OPTICAL",
    "cpo_optical": "CPO_OPTICAL",
    "cpo光互連": "CPO_OPTICAL",
    "cpo光互聯": "CPO_OPTICAL",
    "光互連": "CPO_OPTICAL",
    "光互聯": "CPO_OPTICAL",
    "矽光子": "CPO_OPTICAL",
    "硅光": "CPO_OPTICAL",
    "siph": "CPO_OPTICAL",
    "optical": "CPO_OPTICAL",
    "cowos": "ADV_PACKAGING",
    "pkg": "ADV_PACKAGING",
    "package": "ADV_PACKAGING",
    "packaging": "ADV_PACKAGING",
    "adv_packaging": "ADV_PACKAGING",
    "先進封裝": "ADV_PACKAGING",
    "封裝": "ADV_PACKAGING",
    "soic": "ADV_PACKAGING",
    "cooling": "POWER_COOLING",
    "power": "POWER_COOLING",
    "power_cooling": "POWER_COOLING",
    "散熱": "POWER_COOLING",
    "水冷": "POWER_COOLING",
    "液冷": "POWER_COOLING",
    "電力": "POWER_COOLING",
    "電力液冷": "POWER_COOLING",
    "chip": "AI_CHIPS",
    "chips": "AI_CHIPS",
    "gpu": "AI_CHIPS",
    "ai_chips": "AI_CHIPS",
    "ai_chip": "AI_CHIPS",
    "ai晶片": "AI_CHIPS",
    "晶片": "AI_CHIPS",
    "算力": "AI_CHIPS",
    "asic": "AI_CHIPS",
    "server": "SERVER_ODM",
    "odm": "SERVER_ODM",
    "server_odm": "SERVER_ODM",
    "伺服器": "SERVER_ODM",
    "伺服器odm": "SERVER_ODM",
    "主機板": "SERVER_ODM",
    "robot": "ROBOTICS",
    "robotics": "ROBOTICS",
    "機器人": "ROBOTICS",
    "具身智能": "ROBOTICS",
    "hbm": "HBM_STORAGE",
    "storage": "HBM_STORAGE",
    "hbm_storage": "HBM_STORAGE",
    "儲存": "HBM_STORAGE",
    "記憶體": "HBM_STORAGE",
    "dram": "HBM_STORAGE",
    "all": "ALL",
    "全部": "ALL",
    "全部主題": "ALL",
    "全產業鏈": "ALL",
}

VALID_THEMES = {
    "ALL", "HBM_STORAGE", "CPO_OPTICAL", "POWER_COOLING",
    "ADV_PACKAGING", "AI_CHIPS", "SERVER_ODM", "ROBOTICS"
}


def resolve_industry_theme(theme: Optional[str] = "ALL") -> str:
    """Resolve user input theme alias into standardized uppercase theme ID."""
    if not theme or not str(theme).strip():
        return "ALL"
    raw = str(theme).strip()
    upper = raw.upper()
    if upper in VALID_THEMES:
        return upper
    clean = re.sub(r"[\s\-_/]+", "", raw.lower())
    if not clean:
        return "ALL"
    # 1. Exact match first
    for alias_key, target in THEME_ALIASES.items():
        clean_alias = re.sub(r"[\s\-_/]+", "", alias_key.lower())
        if clean == clean_alias:
            return target
    # 2. Substring match only if length >= 2
    if len(clean) >= 2:
        for alias_key, target in THEME_ALIASES.items():
            clean_alias = re.sub(r"[\s\-_/]+", "", alias_key.lower())
            if clean in clean_alias or clean_alias in clean:
                return target
    return "ALL"


def fetch_industry_chain_themes() -> List[Dict[str, Any]]:
    """Fetch all available industry chain themes from stockdata.david888.com."""
    cache_key = "industry_chain:themes"
    cached = _industry_chain_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/industry-chain/themes")
        if res and res.get("success") and "data" in res:
            data = res["data"]
            _industry_chain_cache.set(cache_key, data)
            return data
        stale = _industry_chain_cache.get_stale(cache_key)
        if stale:
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_industry_chain_graph(theme: str = "ALL") -> Dict[str, Any]:
    """Fetch industry value chain graph topology for a specific theme or ALL."""
    canonical_theme = resolve_industry_theme(theme)
    cache_key = f"industry_chain:graph:{canonical_theme}"
    cached = _industry_chain_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/industry-chain/graph", params={"theme": canonical_theme})
        if res and res.get("success"):
            _industry_chain_cache.set(cache_key, res)
            return res
        stale = _industry_chain_cache.get_stale(cache_key)
        if stale:
            return stale
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_industry_chain_markdown(data: Dict[str, Any]) -> str:
    """Format industry value chain graph into clean Telegram HTML card with pre code block."""
    if not data or not isinstance(data, dict) or not data.get("success"):
        return format_card("AI 產業價值鏈拓撲圖譜", "無產業鏈圖譜資料", emoji="⛓️")

    theme_id = data.get("theme", "ALL")
    theme_names = {
        "ALL": "全產業鏈整合圖譜",
        "CPO_OPTICAL": "CPO 光互連與矽光子",
        "ADV_PACKAGING": "先進封裝 (CoWoS/SoIC)",
        "POWER_COOLING": "電力與散熱液冷",
        "AI_CHIPS": "AI 晶片與核心算力",
        "SERVER_ODM": "伺服器與系統 ODM",
        "ROBOTICS": "機器人與具身智能",
        "HBM_STORAGE": "HBM 與高頻寬記憶體",
    }
    theme_title = theme_names.get(theme_id, theme_id)
    total_nodes = data.get("total_nodes", 0)
    summary = data.get("summary") or ""

    lines = [
        f"主題圖譜: {theme_title} ({theme_id})",
        f"節點總數: {total_nodes} 檔核心標的",
    ]
    if summary:
        lines.append(f"概要: {summary}")
    lines.append("")

    def _format_nodes(title_str: str, nodes: List[Dict[str, Any]], max_n: int = 5):
        if not nodes:
            return
        lines.append(f"[{title_str}]")
        for n in nodes[:max_n]:
            if not isinstance(n, dict):
                continue
            ticker = n.get("ticker", "")
            company = n.get("company", "")
            price = n.get("current_price")
            chg = n.get("change_pct")
            role = n.get("role") or n.get("key_focus") or ""
            streak = n.get("institutional_streak")
            dual = n.get("dual_model_consensus")

            badges = []
            if dual:
                badges.append("雙模型共振")
            if streak:
                badges.append(str(streak))

            badge_str = f" [{'|'.join(badges)}]" if badges else ""
            price_str = f"現價: {price:,.1f}" if price is not None else ""
            chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
            lines.append(f"• {ticker} {company} {price_str}{chg_str}{badge_str}".strip())
            if role:
                lines.append(f"  ↳ {role[:45]}")
        lines.append("")

    _format_nodes("上游核心標的 (Upstream)", data.get("upstream_nodes", []))
    _format_nodes("中游關鍵模組/製造 (Midstream)", data.get("midstream_nodes", []))
    _format_nodes("下游系統整合/終端 (Downstream)", data.get("downstream_nodes", []))

    edges = data.get("edges", [])
    if edges:
        lines.append("[關鍵依賴與傳導關係 (Key Relations)]")
        for e in edges[:6]:
            if not isinstance(e, dict):
                continue
            src = e.get("source", "")
            tgt = e.get("target", "")
            rel = e.get("relation_type", "依賴")
            desc = e.get("desc", "")
            w = e.get("weight")
            w_str = f" (權重:{w})" if w is not None else ""
            lines.append(f"• {src} ➔ {tgt} [{rel}]{w_str}")
            if desc:
                lines.append(f"  ↳ {desc[:45]}")

    pre_content = "\n".join(lines).strip()
    footer = "產業價值鏈拓撲圖譜；點選下方按鈕切換不同 AI 核心主題。"
    return format_card(
        title=f"AI 產業價值鏈拓撲圖譜 ({theme_title})",
        pre_content=pre_content,
        emoji="⛓️",
        footer=footer,
    )


def fetch_tri_bullish_predictions(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch multi-model Tri-Bullish consensus predictions (TimesFM ∩ Timestral ∩ MOIRAI-2)."""
    cache_key = f"tri_bullish:{limit}"
    cached = _tri_bullish_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/predictions/tri-bullish", params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _tri_bullish_cache.set(cache_key, items)
            return items
        stale = _tri_bullish_cache.get_stale(cache_key)
        if stale:
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_dual_bullish_predictions(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch Dual-Bullish consensus predictions."""
    cache_key = f"dual_bullish:{limit}"
    cached = _dual_bullish_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/predictions/dual-bullish", params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _dual_bullish_cache.set(cache_key, items)
            return items
        stale = _dual_bullish_cache.get_stale(cache_key)
        if stale:
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_dual_bearish_predictions(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch Dual-Bearish consensus predictions."""
    cache_key = f"dual_bearish:{limit}"
    cached = _dual_bearish_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/predictions/dual-bearish", params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _dual_bearish_cache.set(cache_key, items)
            return items
        stale = _dual_bearish_cache.get_stale(cache_key)
        if stale:
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_tri_bullish_markdown(items: List[Dict[str, Any]]) -> str:
    """Format Tri-Bullish consensus picks into clean Telegram HTML card."""
    if not items or not isinstance(items, list):
        return format_card("三模型同步看漲共識焦點榜", "目前市場暫無三大時序模型（TimesFM ∩ Timestral ∩ MOIRAI-2）同步看多標的。", emoji="🏆")

    blocks = []
    for i, p in enumerate(items[:10], 1):
        if not isinstance(p, dict):
            continue
        ticker = p.get("ticker", "")
        name = p.get("name", "")
        price = float(p.get("current_price") or 0.0)
        target = float(p.get("predicted_price") or 0.0)
        potential = float(p.get("potential") or 0.0)
        sign = "+" if potential >= 0 else ""

        entry_lines = [
            f"[{i}] {ticker} {name} [三大模型同步看多]",
            f"現價: {price:,.1f} ➔ 綜合預期: {target:,.1f} ({sign}{potential:.1f}%)",
        ]

        # Model potentials breakdown
        tfm_p = p.get("timesfm_potential")
        tms_p = p.get("timestral_potential")
        moi_p = p.get("moirai_potential")
        model_sub = []
        if tfm_p is not None:
            try:
                model_sub.append(f"TimesFM: {float(tfm_p):+.1f}%")
            except (ValueError, TypeError):
                pass
        if tms_p is not None:
            try:
                model_sub.append(f"Timestral: {float(tms_p):+.1f}%")
            except (ValueError, TypeError):
                pass
        if moi_p is not None:
            try:
                model_sub.append(f"MOIRAI: {float(moi_p):+.1f}%")
            except (ValueError, TypeError):
                pass
        if model_sub:
            entry_lines.append(f"模型明細: {' | '.join(model_sub)}")

        # Chips / Fundamentals
        t_net = p.get("trust_net_5d")
        f_net = p.get("foreign_net_5d")
        pe = p.get("pe")
        extra = []
        if t_net is not None:
            try:
                extra.append(f"投信{int(float(t_net)):+d}")
            except (ValueError, TypeError):
                pass
        if f_net is not None:
            try:
                extra.append(f"外資{int(float(f_net)):+d}")
            except (ValueError, TypeError):
                pass
        if pe is not None:
            try:
                extra.append(f"PE:{float(pe):.1f}x")
            except (ValueError, TypeError):
                pass
        if extra:
            entry_lines.append(f"籌碼評價: {' | '.join(extra)}")

        blocks.append("\n".join(entry_lines))

    pre_content = "\n\n".join(blocks) if blocks else "無有效三模型共識資料"
    footer = "TimesFM ∩ Timestral ∩ MOIRAI-2 三大 AI 時序大模型共識推薦。"
    return format_card(
        title="三模型同步看漲共識焦點榜",
        pre_content=pre_content,
        emoji="🏆",
        footer=footer,
    )


def fetch_discovery_signals(limit: int = 6) -> List[Dict[str, Any]]:
    """Fetch academic paper breakthrough discovery signals and mapped tickers."""
    cache_key = f"discovery:signals:{limit}"
    cached = _discovery_signals_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/discovery/signals", params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _discovery_signals_cache.set(cache_key, items)
            return items
        stale = _discovery_signals_cache.get_stale(cache_key)
        if stale:
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def fetch_discovery_candidates(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch frontier technological discovery candidates."""
    cache_key = f"discovery:candidates:{limit}"
    cached = _discovery_candidates_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/discovery/candidates", params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _discovery_candidates_cache.set(cache_key, items)
            return items
        stale = _discovery_candidates_cache.get_stale(cache_key)
        if stale:
            return stale
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_discovery_markdown(data: Any) -> str:
    """Format discovery signals and candidates into Telegram HTML card."""
    signals: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []

    if isinstance(data, list):
        signals = data
    elif isinstance(data, dict):
        signals = data.get("signals") or []
        candidates = data.get("candidates") or []
        if not signals and not candidates and "data" in data and isinstance(data["data"], list):
            sample = data["data"][:1]
            if sample and isinstance(sample[0], dict):
                if "signal_id" in sample[0] or "detected_at" in sample[0]:
                    signals = data["data"]
                else:
                    candidates = data["data"]

    if not signals and not candidates:
        return format_card("產業前沿雷達與學術瓶頸突破", "目前暫無前沿技術突破訊號或候選標的資料。", emoji="🛰️")

    lines = []
    if signals:
        lines.append("[前沿論文技術突破與映射標的]")
        for s in signals[:5]:
            if not isinstance(s, dict):
                continue
            theme = s.get("theme_id", "")
            ticker = s.get("ticker", "")
            title = s.get("title", "")
            content = s.get("content", "")
            score = s.get("sentiment_score")
            dt = str(s.get("detected_at", ""))[:10]
            lines.append(f"• 【{theme}】{ticker} (情感分: {score})")
            if title:
                lines.append(f"  標題: {title[:50]}")
            if content:
                lines.append(f"  內容: {content[:60]}")
            if dt:
                lines.append(f"  時間: {dt}")
        lines.append("")

    if candidates:
        lines.append("[前沿突破潛力候選池]")
        for c in candidates[:5]:
            if not isinstance(c, dict):
                continue
            ticker = c.get("ticker", "")
            name = c.get("name", "")
            mkt = c.get("market", "")
            theme_name = c.get("theme_name", "")
            score = c.get("total_score")
            catalyst = c.get("catalyst_summary", "")
            anchor = c.get("us_anchor", "")
            score_str = f" - 總分: {score:.1f}" if score is not None else ""
            lines.append(f"• {ticker} {name} ({mkt}){score_str}")
            if theme_name:
                lines.append(f"  主題: {theme_name}")
            if catalyst:
                lines.append(f"  催化: {catalyst[:50]}")
            if anchor:
                lines.append(f"  美股錨點: {anchor}")

    pre_content = "\n".join(lines).strip()
    footer = "前沿學術論文與技術瓶頸映射；結合產業鏈 /chain 與即時快訊 /hot 交叉驗證。"
    return format_card(
        title="產業前沿雷達與技術論文瓶頸突破",
        pre_content=pre_content,
        emoji="🛰️",
        footer=footer,
    )


def fetch_portfolio_risk_xray(tickers: List[str], window: int = 60) -> Dict[str, Any]:
    """Fetch multi-market portfolio risk X-ray analysis via POST."""
    clean_tickers = [t.strip().upper() for t in tickers if t and t.strip()]
    cache_key = f"risk_xray:{','.join(sorted(clean_tickers))}:{window}"
    cached = _risk_xray_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        url = f"{STOCKDATA_BASE_URL.rstrip('/')}/api/v1/risk/xray"
        headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
        try:
            resp = requests.post(
                url,
                json={"tickers": clean_tickers, "window": window},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                d = resp.json()
                _risk_xray_cache.set(cache_key, d)
                return d
            logger.warning(f"StockData Risk X-Ray returned status {resp.status_code}")
        except Exception as e:
            logger.error(f"StockData Risk X-Ray error for {clean_tickers}: {e}")
        return _risk_xray_cache.get_stale(cache_key) or {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_portfolio_risk_xray_markdown(data: Dict[str, Any]) -> str:
    """Format Portfolio Risk X-Ray analysis into clean Telegram HTML card."""
    if not data or not isinstance(data, dict) or data.get("status") not in ("ok", "success"):
        return format_card("多市場投資組合風險 X 光片", "無法取得投資組合風險評估資料，請確認標的代碼是否正確。", emoji="🩻")

    vol_total = float(data.get("annualized_volatility_total") or 0.0)
    vol_sleeve = float(data.get("annualized_volatility_risk_sleeve") or 0.0)
    eff_n = float(data.get("effective_n_risk_sleeve") or 0.0)
    available = data.get("available_tickers") or []

    lines = [
        f"監控標的: {', '.join(available) if isinstance(available, list) else str(available)}",
        f"組合年化波動率: {vol_total:.2%}",
        f"風險資產年化波動: {vol_sleeve:.2%}",
        f"有效資產數 (Effective N): {eff_n:.1f}",
        "",
        "[資產配置權重與歐拉波動貢獻 (PCV%)]",
    ]

    contributions = data.get("euler_contributions", [])
    for c in contributions:
        if not isinstance(c, dict):
            continue
        ticker = c.get("ticker", "")
        weight = float(c.get("weight") or 0.0)
        ann_vol = float(c.get("annualized_volatility") or 0.0)
        pcv = float(c.get("percentage_contribution") or 0.0)
        lines.append(f"• {ticker}: 權重 {weight:.1%} | 年化波動 {ann_vol:.1%} | 波動貢獻 PCV: {pcv:.1%}")

    suspects = data.get("corporate_action_suspects", [])
    if suspects:
        lines.append("")
        lines.append("[異常跳空/除權息事件警示]")
        for s in suspects[:3]:
            if not isinstance(s, dict):
                continue
            ticker = s.get("ticker", "")
            dt = s.get("date", "")
            ret_pct = s.get("return_pct", "")
            thresh = float(s.get("threshold") or 0.25)
            lines.append(f"• {ticker} ({dt}): 跳空幅度 {ret_pct} (門檻 {thresh:.0%})")

    pairs = data.get("high_correlation_pairs", [])
    if pairs:
        lines.append("")
        lines.append("[高相關性風險對]")
        for p in pairs[:3]:
            if not isinstance(p, dict):
                continue
            t1 = p.get("ticker1", "")
            t2 = p.get("ticker2", "")
            corr = float(p.get("correlation") or 0.0)
            lines.append(f"• {t1} & {t2}: 相關係數 {corr:.2f}")

    warnings = []
    if data.get("fx_unhedged_warning"):
        warnings.append(data["fx_unhedged_warning"])
    if data.get("calendar_mismatch_warning"):
        warnings.append(data["calendar_mismatch_warning"])
    if warnings:
        lines.append("")
        lines.append("[跨市場風險提示]")
        for w in warnings:
            lines.append(f"• {w}")

    pre_content = "\n".join(lines).strip()
    footer = "歐拉波動分解 (Euler PCV%) 評估各標的對整體組合波動之邊際風險貢獻。"
    return format_card(
        title="多市場投資組合風險 X 光片 (Portfolio Risk X-Ray)",
        pre_content=pre_content,
        emoji="🩻",
        footer=footer,
    )


def fetch_stock_history_trajectory(ticker: str, limit: int = 10) -> Dict[str, Any]:
    """Fetch historical predictions and chip trajectory for a stock."""
    clean_ticker = _normalize_quant_ticker(ticker)
    cache_key = f"stock_history:{clean_ticker}:{limit}"
    cached = _stock_history_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json(f"/api/v1/predictions/history/{quote(clean_ticker, safe='')}", params={"limit": limit})
        if res and res.get("success"):
            _stock_history_cache.set(cache_key, res)
            return res
        stale = _stock_history_cache.get_stale(cache_key)
        if stale:
            return stale
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_stock_history_markdown(data: Dict[str, Any]) -> str:
    """Format stock history predictions trajectory into clean Telegram HTML card."""
    if not data or not isinstance(data, dict):
        return format_card("個股歷史量化預測軌跡", "查無該標的之歷史量化預測軌跡資料。", emoji="📈")

    records = data.get("data")
    if not isinstance(records, list) or not records:
        return format_card("個股歷史量化預測軌跡", "查無該標的之歷史量化預測軌跡資料。", emoji="📈")

    first = records[0] if isinstance(records[0], dict) else {}
    ticker = first.get("ticker") or "未知"
    name = first.get("name") or ""

    lines = [
        f"標的代碼: {ticker} {name}".strip(),
        f"歷史預測紀錄數: {len(records)} 筆",
        "",
    ]

    for r in records[:8]:
        if not isinstance(r, dict):
            continue
        ts = r.get("timestamp") or r.get("created_at") or "歷史時序"
        ts_display = str(ts)[:10]
        model = r.get("model_name") or "時序模型"
        cur = float(r.get("current_price") or 0.0)
        pred = float(r.get("predicted_price") or 0.0)
        pot = float(r.get("potential") or 0.0)
        sign = "+" if pot >= 0 else ""
        t_net = r.get("trust_net_5d")
        f_net = r.get("foreign_net_5d")

        chips = []
        if t_net is not None:
            try:
                chips.append(f"投信{int(float(t_net)):+d}")
            except (ValueError, TypeError):
                pass
        if f_net is not None:
            try:
                chips.append(f"外資{int(float(f_net)):+d}")
            except (ValueError, TypeError):
                pass
        chip_str = f" [{'|'.join(chips)}]" if chips else ""

        lines.append(f"• [{ts_display}] {model}: 現價 {cur:,.1f} ➔ 預測 {pred:,.1f} ({sign}{pot:.1f}%){chip_str}")

    pre_content = "\n".join(lines).strip()
    footer = "歷史時序預測軌跡；可搭配 /chip 籌碼與 /s K線圖綜合研判。"
    return format_card(
        title=f"個股歷史量化預測軌跡 ({ticker})",
        pre_content=pre_content,
        emoji="📈",
        footer=footer,
    )


def fetch_model_performance_scorecard(market: str = "ALL", horizon: int = 5) -> Dict[str, Any]:
    """Fetch model performance backtest scorecard."""
    clean_market = market.strip().upper()
    cache_key = f"perf_models:{clean_market}:{horizon}"
    cached = _model_performance_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        params: Dict[str, Any] = {"horizon": horizon}
        if clean_market in ("TW", "US", "JP"):
            params["market"] = clean_market
        res = _get_json("/api/v1/performance/models", params=params)
        if res and isinstance(res, dict):
            _model_performance_cache.set(cache_key, res)
            return res
        stale = _model_performance_cache.get_stale(cache_key)
        if stale:
            return stale
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_model_performance_markdown(data: Dict[str, Any]) -> str:
    """Format model performance backtest scorecard into clean Telegram HTML card."""
    if not data or not isinstance(data, dict):
        return format_card("時序模型回測計分卡", "無回測計分卡資料", emoji="📊")

    status = data.get("status") or "normal"
    excluded = int(data.get("excluded_count") or 0)
    score_ver = data.get("score_version") or "forecast-score-v1"
    records = data.get("data", [])

    lines = [
        f"評估狀態: {status}",
        f"計分版本: {score_ver}",
        f"已排除樣本數: {excluded:,} 筆",
        "",
    ]

    if records:
        lines.append("[模型歷史預測準確率與回測表現]")
        for r in records[:5]:
            if not isinstance(r, dict):
                continue
            name = r.get("model_name", "Model")
            acc = r.get("directional_accuracy")
            mae = r.get("mae")
            acc_str = f"方向勝率: {float(acc):.1%}" if acc is not None else ""
            mae_str = f"MAE: {float(mae):.2f}" if mae is not None else ""
            lines.append(f"• {name}: {acc_str} | {mae_str}".strip(" |"))
    else:
        lines.append("目前回測樣本累積中 (insufficient_data)，大模型樣本達標後將自動公布完整計分卡。")

    pre_content = "\n".join(lines).strip()
    footer = "時序大模型歷史樣本預測準確度回測評估計分卡。"
    return format_card(
        title="時序模型回測計分卡 (Model Performance Scorecard)",
        pre_content=pre_content,
        emoji="📊",
        footer=footer,
    )


def fetch_canary_health() -> Dict[str, Any]:
    """Fetch health probe and latency status for all 8 upstream data sources."""
    cache_key = "canary_health"
    cached = _canary_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/stats/canary-health")
        if res and isinstance(res, dict) and "sources" in res:
            _canary_cache.set(cache_key, res)
            return res
        stale = _canary_cache.get_stale(cache_key)
        if stale:
            return stale
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_canary_health_markdown(data: Dict[str, Any]) -> str:
    """Format canary health status into clean Telegram HTML card."""
    if not data or not isinstance(data, dict):
        return format_card("上游資料源金絲雀健康度", "無法取得資料源健康狀態資料。", emoji="🐤")

    status = data.get("status", "unknown")
    checked_at = str(data.get("checked_at", "未知時間"))[:19].replace("T", " ")
    sources = data.get("sources", {})

    status_icon = "🟢" if status == "healthy" else ("🟡" if status == "degraded" else "🔴")
    lines = [
        f"系統整體狀態: {status_icon} {status.upper()}",
        f"最近檢測時間: {checked_at} (UTC)",
        f"監控資料源數: {len(sources)} 個",
        "",
        "[各核心資料源即時連線與延遲指標]",
    ]

    for name, info in sources.items():
        if not isinstance(info, dict):
            continue
        s_stat = info.get("status", "unknown")
        lat = info.get("latency_ms")
        lat_str = f" ({float(lat):,.0f}ms)" if lat is not None else " (N/A)"
        badge = "🟢 正常" if s_stat == "healthy" else ("🟡 延遲/降級" if "degraded" in s_stat else "🔴 異常")
        lines.append(f"• {name.upper()}: {badge}{lat_str}")
        reason = info.get("sanitized_reason")
        if reason:
            lines.append(f"  ↳ 原因: {str(reason)[:60]}")

    pre_content = "\n".join(lines).strip()
    footer = "金絲雀健康探針每 2 分鐘定期巡檢各核心資料源可用性。"
    return format_card(
        title="上游資料源金絲雀健康度 (Canary Health)",
        pre_content=pre_content,
        emoji="🐤",
        footer=footer,
    )


def fetch_podcast_intel(limit: int = 8) -> Dict[str, Any]:
    """Fetch top podcast discussion entities and latest episodes."""
    cache_key = f"podcast_intel:{limit}"
    cached = _podcast_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        topics_res = _get_json("/api/v1/podcast/topics", params={"limit": max(5, limit)})
        episodes_res = _get_json("/api/v1/podcast/episodes", params={"limit": limit})
        if not topics_res and not episodes_res:
            stale = _podcast_cache.get_stale(cache_key)
            if stale:
                return stale
        topics = topics_res.get("data", []) if topics_res and isinstance(topics_res, dict) else []
        episodes = episodes_res.get("data", []) if episodes_res and isinstance(episodes_res, dict) else []
        result = {
            "success": True,
            "topics": topics,
            "episodes": episodes,
        }
        if topics or episodes:
            _podcast_cache.set(cache_key, result)
        return result

    return _sd_singleflight.run(cache_key, _fetch)


def format_podcast_intel_markdown(data: Dict[str, Any]) -> str:
    """Format podcast intelligence into clean Telegram HTML card."""
    if not data or not isinstance(data, dict):
        return format_card("頂級財經與科技 Podcast 話題熱榜", "暫無 Podcast 話題與單集情報。", emoji="🎙️")

    topics = data.get("topics", [])
    episodes = data.get("episodes", [])
    if not topics and not episodes:
        return format_card("頂級財經與科技 Podcast 話題熱榜", "暫無 Podcast 話題與單集情報。", emoji="🎙️")

    lines = []
    if topics:
        lines.append("[熱門討論實體排行 (Top Entities)]")
        topic_strs = []
        for i, t in enumerate(topics[:8], 1):
            if isinstance(t, dict):
                top_name = t.get("topic", "")
                cnt = t.get("count", 0)
                topic_strs.append(f"[{i}] {top_name} ({cnt}次)")
        lines.append("  ".join(topic_strs[:4]))
        if len(topic_strs) > 4:
            lines.append("  ".join(topic_strs[4:8]))
        lines.append("")

    if episodes:
        lines.append("[最新科技財經單集精選]")
        for ep in episodes[:4]:
            if not isinstance(ep, dict):
                continue
            title = str(ep.get("title") or "單集分享")
            channel = str(ep.get("channel_title") or ep.get("channel_name") or "Podcast")
            dur = str(ep.get("duration_formatted") or "")
            dur_str = f", {dur}" if dur else ""
            tldr = str(ep.get("tldr_zh_tw") or ep.get("ai_takeaways") or ep.get("summary") or "")
            tickers = ep.get("tickers") or ep.get("mentioned_tickers") or []
            lines.append(f"• {title[:40]} ({channel}{dur_str})")
            if tldr:
                lines.append(f"  核心摘要: {tldr[:70]}...")
            if tickers:
                lines.append(f"  提及標的: {', '.join(tickers)}")

    pre_content = "\n".join(lines).strip()
    footer = "精選頂級科技與財經 Podcast 原生內容與 AI 實體提取。"
    return format_card(
        title="頂級財經與科技 Podcast 話題熱榜",
        pre_content=pre_content,
        emoji="🎙️",
        footer=footer,
    )


def fetch_watchlist() -> Dict[str, Any]:
    """Fetch DuckDB cloud watchlist and predictions."""
    cache_key = "watchlist:default"
    cached = _watchlist_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json("/api/v1/watchlist")
        if res and isinstance(res, dict) and res.get("success"):
            _watchlist_cache.set(cache_key, res)
            return res
        stale = _watchlist_cache.get_stale(cache_key)
        if stale:
            return stale
        return {"success": False, "items": []}

    return _sd_singleflight.run(cache_key, _fetch)


def format_watchlist_markdown(data: Dict[str, Any]) -> str:
    """Format DuckDB watchlist into clean Telegram HTML card."""
    if not data or not isinstance(data, dict) or not data.get("success"):
        return format_card("DuckDB 雲端自選股監控清單", "無法取得雲端自選股清單資料。", emoji="⭐")

    items = data.get("items", [])
    if not items:
        return format_card(
            "DuckDB 雲端自選股監控清單",
            "目前自選股監控清單為空。\n\n💡 可透過 StockData Web 端或 API 新增關注標的，系統將自動啟動跨模型每日預測追蹤。",
            emoji="⭐"
        )

    lines = [
        f"自選股總數: {len(items)} 檔",
        "",
    ]

    for i, it in enumerate(items[:10], 1):
        if not isinstance(it, dict):
            continue
        ticker = it.get("ticker", "")
        name = it.get("name", "")
        cur = float(it.get("current_price") or 0.0)
        pred = float(it.get("predicted_price") or 0.0)
        pot = float(it.get("potential") or 0.0)
        tags = it.get("tags") or ""
        lines.append(f"[{i}] {ticker} {name}: 現價 {cur:,.1f} ➔ 預測 {pred:,.1f} ({pot:+.1f}%)")
        if tags:
            lines.append(f"  標籤: {tags[:45]}")

    pre_content = "\n".join(lines).strip()
    footer = "DuckDB 雲端自選股跨模型同步追蹤清單。"
    return format_card(
        title="DuckDB 雲端自選股監控清單",
        pre_content=pre_content,
        emoji="⭐",
        footer=footer,
    )


# ==========================================
# 10. Extended LangChain Tool Definitions
# ==========================================

@tool
def get_industry_chain(theme: str = "ALL") -> Dict[str, Any]:
    """
    Fetches the AI Industry Value Chain graph topology (Upstream/Midstream/Downstream nodes, current prices, potentials, and dependencies like 大客戶依賴, 資本開支):
    - Supported themes: ALL, CPO_OPTICAL (cpo), ADV_PACKAGING (cowos, pkg), POWER_COOLING (cooling, power), AI_CHIPS (chip, gpu), SERVER_ODM (server, odm), ROBOTICS (robot), HBM_STORAGE (hbm)
    Use when users ask:
    - '查詢 CPO 光互連/矽光子產業鏈上下游標的'
    - 'CoWoS 先進封裝供應鏈關係與關鍵台美股'
    - '散熱液冷或 AI 晶片價值鏈圖譜'
    """
    logger.info(f"=== [Tool] get_industry_chain called for theme: {theme} ===")
    canonical_theme = resolve_industry_theme(theme)
    data = fetch_industry_chain_graph(canonical_theme)
    summary = format_industry_chain_markdown(data)
    return {
        "theme": canonical_theme,
        "graph_data": data,
        "formatted_summary": summary,
    }


@tool
def get_tri_bullish_predictions_tool(limit: int = 8) -> Dict[str, Any]:
    """
    Fetches the Tri-Bullish Consensus stock leaderboard where all 3 foundational time-series models (Google TimesFM ∩ Mistral Timestral-209M ∩ Salesforce MOIRAI-2) simultaneously predict strong bullish gains.
    Use when users ask:
    - '有哪些三模型同步看漲的股票？'
    - 'TimesFM、Timestral 與 MOIRAI 同步看多的交集標的'
    - '三大時序模型共識推薦'
    """
    logger.info(f"=== [Tool] get_tri_bullish_predictions_tool called with limit: {limit} ===")
    items = fetch_tri_bullish_predictions(limit)
    summary = format_tri_bullish_markdown(items)
    return {
        "count": len(items),
        "predictions": items,
        "formatted_summary": summary,
    }


@tool
def get_discovery_signals_tool(limit: int = 6) -> Dict[str, Any]:
    """
    Fetches technological bottleneck breakthroughs and academic paper discovery radar signals (arXiv frontier breakthroughs mapped to Taiwan and US listed equities).
    Use when users ask:
    - '最新學術論文突破映射受惠股票'
    - '產業前沿技術雷達與突破候選標的'
    - '前沿論文發現訊號'
    """
    logger.info(f"=== [Tool] get_discovery_signals_tool called with limit: {limit} ===")
    signals = fetch_discovery_signals(limit)
    candidates = fetch_discovery_candidates(limit)
    summary = format_discovery_markdown({"signals": signals, "candidates": candidates})
    return {
        "signals_count": len(signals),
        "candidates_count": len(candidates),
        "signals": signals,
        "candidates": candidates,
        "formatted_summary": summary,
    }


@tool
def get_portfolio_risk_xray_tool(tickers: str, window: int = 60) -> Dict[str, Any]:
    """
    Computes multi-market portfolio risk X-ray analysis, annualized total volatility, asset weights, and Euler Percentage Contribution to Volatility (PCV%), plus corporate action/jump alerts.
    - tickers: comma-separated or space-separated ticker symbols (e.g. '2330.TW,NVDA,2317.TW')
    - window: historical lookback window in trading days (default: 60)
    Use when users ask:
    - '幫我做投資組合風險 X 光片'
    - '計算我持股的年化波動度與歐拉風險貢獻 (PCV%)'
    - '多市場投資組合波動風險診斷'
    """
    logger.info(f"=== [Tool] get_portfolio_risk_xray_tool called for: {tickers} (window: {window}) ===")
    raw_list = re.split(r"[,;\s]+", (tickers or "").strip())
    ticker_list = [t.strip().upper() for t in raw_list if t.strip()]
    data = fetch_portfolio_risk_xray(ticker_list, window)
    summary = format_portfolio_risk_xray_markdown(data)
    return {
        "tickers": ticker_list,
        "window": window,
        "risk_data": data,
        "formatted_summary": summary,
    }


@tool
def get_stock_history_trajectory_tool(ticker: str, limit: int = 10) -> Dict[str, Any]:
    """
    Fetches the historical quantitative predictions trajectory and institutional chips flow across prior trading days for a specific stock.
    Use when users ask:
    - '查詢台積電 2330 過去幾天模型的預測目標價軌跡'
    - '個股歷史量化預測驗證與法人買賣超走勢'
    """
    logger.info(f"=== [Tool] get_stock_history_trajectory_tool called for: {ticker} ===")
    data = fetch_stock_history_trajectory(ticker, limit)
    summary = format_stock_history_markdown(data)
    return {
        "ticker": ticker,
        "history_data": data,
        "formatted_summary": summary,
    }


@tool
def get_model_performance_scorecard_tool(market: str = "ALL", horizon: int = 5) -> Dict[str, Any]:
    """
    Fetches the historical prediction accuracy scorecard and backtest metrics across time-series models (TimesFM, Timestral, MOIRAI-2).
    - market: 'ALL', 'TW', 'US', or 'JP'
    - horizon: forecast horizon in days (default: 5)
    Use when users ask:
    - '各時序大模型的預測準確率與回測計分卡'
    - 'TimesFM 或 Timestral 在台股/美股的勝率如何？'
    """
    logger.info(f"=== [Tool] get_model_performance_scorecard_tool called for market: {market} ===")
    data = fetch_model_performance_scorecard(market, horizon)
    summary = format_model_performance_markdown(data)
    return {
        "market": market,
        "horizon": horizon,
        "performance_data": data,
        "formatted_summary": summary,
    }


@tool
def get_canary_health_tool() -> Dict[str, Any]:
    """
    Fetches the real-time probe latency and health status across all 8 core upstream data sources (TWSE, TPEx, yfinance, Investing, Polymarket, BigGo, arXiv).
    Use when users ask:
    - '資料源連線正常嗎？'
    - '查詢金絲雀健康度與各資料源延遲'
    - '系統上游 API 狀態'
    """
    logger.info("=== [Tool] get_canary_health_tool called ===")
    data = fetch_canary_health()
    summary = format_canary_health_markdown(data)
    return {
        "health_data": data,
        "formatted_summary": summary,
    }


@tool
def get_podcast_intel_tool(limit: int = 8) -> Dict[str, Any]:
    """
    Fetches top tech & finance podcast entity discussions (OpenAI, Anthropic, NVIDIA, etc.) and latest episode AI takeaways.
    Use when users ask:
    - '科技財經 Podcast 最近在討論什麼？'
    - 'Podcast 熱門話題榜與單集摘要'
    """
    logger.info(f"=== [Tool] get_podcast_intel_tool called with limit: {limit} ===")
    data = fetch_podcast_intel(limit)
    summary = format_podcast_intel_markdown(data)
    return {
        "podcast_data": data,
        "formatted_summary": summary,
    }


@tool
def get_watchlist_tool() -> Dict[str, Any]:
    """
    Fetches the DuckDB cloud-synced watchlist and multi-model forecast tracking for user's watched tickers.
    Use when users ask:
    - '查詢我的雲端自選股'
    - '自選股清單與各標的最新潛力'
    """
    logger.info("=== [Tool] get_watchlist_tool called ===")
    data = fetch_watchlist()
    summary = format_watchlist_markdown(data)
    return {
        "watchlist_data": data,
        "formatted_summary": summary,
    }

