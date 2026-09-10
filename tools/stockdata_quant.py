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

import json
import logging
from typing import Any, Dict, List, Optional

import requests

from config import STOCKDATA_BASE_URL
from tools.cache_util import TTLCache, SingleFlight

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
            _macro_cache.set(cache_key, res)
            return res
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_macro_regime_markdown(data: Dict[str, Any]) -> str:
    """Format macro regime into clean Telegram Markdown."""
    if not data or not data.get("success"):
        return "⚠️ 目前暫時無法取得大盤風控資料，請稍後重試。"

    m_name = "🇹🇼 台股市場" if data.get("market") == "TW" else "🇺🇸 美股市場"
    regime = data.get("regime_name", "評估中")
    exposure = data.get("exposure", 0.0)
    exp_pct = int(round(exposure * 100))
    vix = data.get("vix", 0.0)

    # Status badges
    spy_status = "✅ 季線上" if data.get("spy_above_ma60") else "⚠️ 跌破季線"
    twii_status = "✅ 季線上" if data.get("twii_above_ma60") else "⚠️ 跌破季線"
    sox_status = "✅ 季線上" if data.get("sox_above_ma60") else "⚠️ 跌破季線"

    # Exposure bar
    filled = exp_pct // 10
    bar = "█" * filled + "░" * (10 - filled)

    lines = [
        f"🛡️ **【大盤風控制度與部位曝險指南】**",
        f"🌐 **監控市場**：{m_name}",
        f"📊 **市場狀態**：`{regime}`",
        f"💼 **建議投資曝險**：`[{bar}]` **{exp_pct}%**",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📈 **核心指數技術均線**：",
        f"  • 台股加權 (`^TWII`)：{twii_status}",
        f"  • 美股標普 (`SPY`)：{spy_status}",
        f"  • 費城半導體 (`^SOX`)：{sox_status}",
        f"  • VIX 恐慌指數：`{vix:.2f}`",
    ]

    warnings = data.get("warnings", [])
    if warnings:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("⚠️ **關鍵風控警語**：")
        for w in warnings[:3]:
            lines.append(f"  • {w}")

    lines.append("")
    lines.append("💡 *量化建議：請依建議曝險動態調節持股水位，若科技/半導體破季線請嚴格防守。*")
    return "\n".join(lines)


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
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_resonance_markdown(picks: List[Dict[str, Any]], title: str = "") -> str:
    """Format resonance picks into Telegram Markdown."""
    if not picks:
        return "👑 **多模型共振推薦選股**\n\n目前市場暫無觸發共振門檻之焦點標的，建議觀望或查看大盤風控。"

    header = title if title else "👑 **【多模型交集共振焦點選股推薦】**"
    lines = [
        header,
        "*(玄鐵均線回調 ∩ 三大法人鎖碼 ∩ LSTM/TimesFM看漲 ∩ 估值合理)*",
        ""
    ]

    for i, p in enumerate(picks[:10], 1):
        ticker = p.get("ticker", "未知")
        name = p.get("name", "")
        t_display = f"{ticker} {name}".strip()
        price = p.get("current_price", 0.0)
        target = p.get("predicted_price", 0.0)
        potential = p.get("potential", 0.0)
        model = p.get("model_name", "Quant")
        strategy = p.get("strategy_type", "")
        pe = p.get("pe")
        t_net = p.get("trust_net_5d", 0)
        f_net = p.get("foreign_net_5d", 0)

        # Tags / Badges
        badges = []
        if "玄鐵" in strategy:
            badges.append("🗡️玄鐵")
        if "TimesFM" in model:
            badges.append("🧠TimesFM")
        elif "LSTM" in model:
            badges.append("📈LSTM")
        if t_net and t_net > 0:
            badges.append(f"投信+{t_net}")
        if f_net and f_net > 0:
            badges.append(f"外資+{f_net}")

        badge_str = f" [{' | '.join(badges)}]" if badges else ""

        sign = "+" if potential >= 0 else ""
        lines.append(f"*{i}. {t_display}*{badge_str}")
        lines.append(f"  💰 現價: `{price:,.1f}` ➔ 預期: `{target:,.1f}` (`{sign}{potential:.1f}%`)")
        extra = []
        if pe:
            extra.append(f"PE: `{pe:.1f}x`")
        if p.get("risk_reward_ratio"):
            extra.append(f"盈虧比: `{p['risk_reward_ratio']:.2f}`")
        if extra:
            lines.append(f"  📊 {' | '.join(extra)}")
        lines.append("")

    lines.append("⚠️ *提醒：共振選股為多重模型交集訊號，進場前請先執行 /macro 確認整體部位曝險。*")
    return "\n".join(lines)


# ==========================================
# 3. Google TimesFM 5-Day Forecast (時序大模型)
# ==========================================

def fetch_timesfm_predictions(action: str = "bullish", limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch TimesFM top bullish or bearish predictions with Risk/Reward ratios."""
    ep = "/api/v1/predictions/timesfm/top-bearish" if "bear" in action.lower() or "跌" in action else "/api/v1/predictions/timesfm/top-bullish"
    cache_key = f"timesfm:{action}:{limit}"
    cached = _timesfm_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        res = _get_json(ep, params={"limit": limit})
        if res and res.get("success") and "data" in res:
            items = res["data"]
            _timesfm_cache.set(cache_key, items)
            return items
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_timesfm_markdown(items: List[Dict[str, Any]], is_bearish: bool = False) -> str:
    """Format TimesFM predictions into Telegram Markdown."""
    if not items:
        return "🧠 **Google TimesFM 時序大模型預測**\n\n查無相關預測數據。"

    title = "🧠 **【Google TimesFM 5日看跌避險榜】**" if is_bearish else "🧠 **【Google TimesFM 5日時序大模型看漲榜】**"
    lines = [
        title,
        "*(Google Research 預訓練 500M 時序基礎模型 + 真實盈虧比 RR 排行)*",
        ""
    ]

    for i, p in enumerate(items[:10], 1):
        ticker = p.get("ticker", "未知")
        name = p.get("name", "")
        t_display = f"{ticker} {name}".strip()
        price = p.get("current_price", 0.0)
        target = p.get("predicted_price", 0.0)
        potential = p.get("potential", 0.0)
        rr = p.get("risk_reward_ratio")

        sign = "+" if potential >= 0 else ""
        lines.append(f"*{i}. {t_display}*")
        lines.append(f"  🎯 現價: `{price:,.1f}` ➔ 5日中位目標: `{target:,.1f}` (`{sign}{potential:.1f}%`)")
        
        info = []
        if rr is not None:
            info.append(f"⚖️ 盈虧比: `{rr:.2f}`")
        if p.get("pe"):
            info.append(f"PE: `{p['pe']:.1f}x`")
        if info:
            lines.append(f"  {' | '.join(info)}")
        lines.append("")

    lines.append("💡 *指標說明：盈虧比 RR >= 1.5 且看漲具備統計顯著性，P10 可作為嚴格下行停損參考點。*")
    return "\n".join(lines)


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
        return []

    return _sd_singleflight.run(cache_key, _fetch)


def format_xuantie_markdown(items: List[Dict[str, Any]]) -> str:
    """Format Xuantie pullbacks into Telegram Markdown."""
    if not items:
        return "🗡️ **玄鐵重劍波段回調策略**\n\n目前市場無回踩季線/半年線支撐之標的。"

    lines = [
        "🗡️ **【玄鐵重劍：MA60/120 均線波段回調買點】**",
        "*(順大勢 MA60>120 向上 ∩ 逆小勢回踩支撐帶 ±3% 起漲買點)*",
        ""
    ]

    for i, p in enumerate(items[:10], 1):
        ticker = p.get("ticker", "未知")
        name = p.get("name", "")
        t_display = f"{ticker} {name}".strip()
        price = p.get("current_price", 0.0)
        target = p.get("predicted_price", 0.0)
        potential = p.get("potential", 0.0)
        pullback_type = p.get("pullback_type") or "季線/半年線支撐"
        ma60 = p.get("ma60")
        ma120 = p.get("ma120")

        lines.append(f"*{i}. {t_display}* — `{pullback_type}`")
        sign = "+" if potential >= 0 else ""
        lines.append(f"  💰 現價: `{price:,.1f}` ➔ 預期: `{target:,.1f}` (`{sign}{potential:.1f}%`)")
        ma_info = []
        if ma60:
            ma_info.append(f"MA60: `{ma60:.1f}`")
        if ma120:
            ma_info.append(f"MA120: `{ma120:.1f}`")
        if ma_info:
            lines.append(f"  📐 {' | '.join(ma_info)}")
        lines.append("")

    lines.append("💡 *策略精粹：重劍無鋒，大巧不工。不追高突圍，專注季線半年線強支撐低吸。*")
    return "\n".join(lines)


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
        return {}

    return _sd_singleflight.run(cache_key, _fetch)


def format_broker_summary_markdown(data: Dict[str, Any]) -> str:
    """Format broker summary into Telegram Markdown."""
    if not data or "top_buyers" not in data:
        return "🏢 **券商關鍵主力分點進出**\n\n查無該標的近期的券商分點買賣資料（僅支援台股上市公司，如 2330.TW）。"

    ticker = data.get("ticker", "")
    days = data.get("days", 20)
    start_d = data.get("start_date", "")
    end_d = data.get("end_date", "")

    buyers = data.get("top_buyers", [])
    sellers = data.get("top_sellers", [])

    lines = [
        f"🏢 **【{ticker}】近 {days} 日券商主力關鍵分點排行**",
        f"📅 **統計區間**：`{start_d}` ~ `{end_d}`",
        "━━━━━━━━━━━━━━━━━━━━",
        "🟢 **主力買超分點 Top 5**："
    ]

    for i, b in enumerate(buyers[:5], 1):
        b_name = b.get("broker_name", "未知分點")
        net = int(round(b.get("total_net", 0)))
        buy = int(round(b.get("total_buy", 0)))
        sell = int(round(b.get("total_sell", 0)))
        sign = "+" if net > 0 else ""
        lines.append(f"  {i}. **{b_name}**：`{sign}{net:,} 張` (買: `{buy:,}` | 賣: `{sell:,}`)")

    lines.append("")
    lines.append("🔴 **主力賣超分點 Top 5**：")
    for i, s in enumerate(sellers[:5], 1):
        s_name = s.get("broker_name", "未知分點")
        net = int(round(s.get("total_net", 0)))
        buy = int(round(s.get("total_buy", 0)))
        sell = int(round(s.get("total_sell", 0)))
        lines.append(f"  {i}. **{s_name}**：`{net:,} 張` (買: `{buy:,}` | 賣: `{sell:,}`)")

    lines.append("")
    lines.append("💡 *分析心法：外資常透過港商麥格理、高盛、摩根大通下單；本土主力常盤踞於地緣或特選券商分點。*")
    return "\n".join(lines)


# ==========================================
# 6. Structural Calendars & Macro Catalysts
# ==========================================

def fetch_calendar_data(category: str = "all") -> Dict[str, Any]:
    """Fetch structural investing calendars (earnings, economics, fed-rate, commodities)."""
    cache_key = f"cal:{category}"
    cached = _calendar_cache.get(cache_key)
    if cached is not None:
        return cached

    def _fetch():
        result = {}
        if category in ("all", "fed"):
            fed_data = _get_json("/api/v1/macro/investing/fed-rate")
            if fed_data and fed_data.get("success"):
                result["fed"] = fed_data.get("data", {})

        if category in ("all", "earn"):
            earn_data = _get_json("/api/v1/macro/investing/earnings-calendar")
            if earn_data and earn_data.get("success"):
                result["earnings"] = earn_data.get("data", [])

        if category in ("all", "econ"):
            econ_data = _get_json("/api/v1/macro/investing/economic-calendar")
            if econ_data and econ_data.get("success"):
                result["economic"] = econ_data.get("data", [])

        if category in ("all", "comm"):
            comm_data = _get_json("/api/v1/macro/investing/commodities")
            if comm_data and comm_data.get("success"):
                result["commodities"] = comm_data.get("data", {})

        _calendar_cache.set(cache_key, result)
        return result

    return _sd_singleflight.run(cache_key, _fetch)


def format_calendar_markdown(data: Dict[str, Any], cat: str = "all") -> str:
    """Format calendar and catalyst data into Telegram Markdown."""
    lines = ["📅 **【全球總經與美股重磅行事曆】**", ""]

    if "fed" in data:
        fed = data["fed"]
        lines.append("🏦 **CME FedWatch 官方聯準會利率路徑**：")
        lines.append(f"  • 下次會議日期：`{fed.get('meeting_date', '近期')}`")
        lines.append(f"  • 更新時間：`{fed.get('updated_at', '')}`")
        probs = fed.get("probabilities", [])
        for p in probs[:3]:
            rate = p.get("rate_range", "")
            prob = p.get("probability", "")
            lines.append(f"    - 利率區間 `{rate}`：**{prob}**")
        lines.append("")

    if "earnings" in data:
        earns = data["earnings"]
        lines.append("💼 **美股重磅企業近期財報行事曆**：")
        for e in earns[:5]:
            t = e.get("ticker", "")
            name = e.get("name", "")
            d = e.get("date", "")
            eps = e.get("eps_forecast", "N/A")
            lines.append(f"  • `{t}` {name}：`{d}` (預估EPS: `{eps}`)")
        lines.append("")

    if "economic" in data:
        econs = data["economic"]
        lines.append("🌐 **全球重要總經指標公布行事曆**：")
        for ec in econs[:5]:
            country = ec.get("country", "")
            time_str = ec.get("time", "")
            ev = ec.get("event", "")
            lines.append(f"  • `[{country}] {time_str}`：{ev}")
        lines.append("")

    if "commodities" in data:
        comm = data["commodities"]
        lines.append("🪙 **大宗商品週期行情總結**：")
        for k, v in comm.items():
            if isinstance(v, dict):
                c_name = v.get("name", k)
                d_chg = v.get("daily_change", "0")
                sign = "+" if not str(d_chg).startswith("-") else ""
                lines.append(f"  • {c_name}：日漲跌 `{sign}{d_chg}%` ({v.get('indicator', '')})")
        lines.append("")

    lines.append("💡 *前瞻日曆由 stockdata.david888.com 實時自動同步。*")
    return "\n".join(lines)


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
    is_bear = "bear" in ticker_or_type.lower() or "跌" in ticker_or_type
    items = fetch_timesfm_predictions("bearish" if is_bear else "bullish", limit)
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
    data = fetch_calendar_data(category)
    summary = format_calendar_markdown(data, cat=category)
    return {
        "category": category,
        "data": data,
        "formatted_summary": summary
    }
