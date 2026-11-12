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
USER_AGENT = "telegram-bot-stock2/2.14 (888 Stock Quant Client)"


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
