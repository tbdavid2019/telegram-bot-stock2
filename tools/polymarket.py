"""Polymarket prediction market intelligence tools backed by the 2MD endpoint cluster.

Provides:
- 100% free, keyless Polymarket Gamma API integration
- Bypasses Taiwan ISP DNS sinkhole (182.173.0.181) via 2MD proxy cluster
- Anti-thundering-herd with SingleFlight and TTLCache
- Macro, Fed interest rates, elections, IPOs, and market sentiment probability extraction
- Progress bar indicators and Telegram markdown formatters
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from config import TWOMD_SEARCH_ENDPOINTS
from tools.cache_util import TTLCache, SingleFlight

try:
    from langchain_core.tools import tool
except ImportError:  # pragma: no cover
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

# Cache & Concurrency
_pm_cache = TTLCache(default_ttl=300.0, max_size=300)  # 5 minutes TTL
_pm_singleflight = SingleFlight()

# Common keywords mapped to Polymarket tags
KEYWORD_TAG_MAP = {
    "fed": "fed",
    "rate": "fed",
    "rates": "fed",
    "interest": "fed",
    "降息": "fed",
    "升息": "fed",
    "聯準會": "fed",
    "利率": "fed",
    "economy": "economy",
    "recession": "economy",
    "衰退": "economy",
    "通膨": "economy",
    "cpi": "economy",
    "gdp": "economy",
    "politics": "politics",
    "election": "politics",
    "trump": "politics",
    "川普": "politics",
    "大選": "politics",
    "關稅": "politics",
    "tariff": "politics",
    "tariffs": "politics",
    "crypto": "crypto",
    "btc": "crypto",
    "bitcoin": "crypto",
    "eth": "crypto",
    "ethereum": "crypto",
    "比特幣": "crypto",
    "以太坊": "crypto",
    "ai": "ai",
    "openai": "ai",
    "anthropic": "ai",
    "nvidia": "ai",
    "輝達": "ai",
    "人工智慧": "ai",
    "business": "business",
    "ipo": "business",
    "上市": "business",
}

# Negative sports patterns to filter out when user queries macro/financial predictions
SPORTS_PATTERNS = [
    r"\bvs\.?\b", r"\bv\b", r"\bO/U\b", r"\bSpread:\b", r"\bOver/Under\b",
    r"\bATP\b", r"\bWTA\b", r"\bNBA\b", r"\bNFL\b", r"\bMLB\b", r"\bUFC\b",
    r"\bPremier League\b", r"\bChampions League\b", r"\bCounter-Strike\b",
    r"\bEsports\b", r"\bLeague of Legends\b", r"\bValorant\b"
]


def _parse_2md_content(text: str) -> Any:
    """Extract and parse JSON from 2MD reader wrapper or JSON envelope."""
    if not text:
        return None

    # Check for Korean legal block page (e.g. from 2md.glsoft.ai)
    if "법적 사유로 이용 불가" in text:
        raise ValueError("Korean ISP legal block encountered on this node")

    data = None
    try:
        data = json.loads(text)
    except Exception:
        if "Markdown Content:" in text:
            clean = text.split("Markdown Content:", 1)[1].strip()
            data = json.loads(clean)
        else:
            raise

    # Handle 2MD API JSON envelope: {"code": 200, "data": {"content": "..."}}
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict) and "content" in data["data"]:
            inner = data["data"]["content"]
            if isinstance(inner, str):
                return json.loads(inner)
            return inner
        if "data" in data and isinstance(data["data"], list):
            return data["data"]

    return data


def _fetch_polymarket_api(endpoint_path: str, timeout: float = 8.5) -> Optional[Any]:
    """Fetch Polymarket API via 2MD cluster with failover."""
    target_url = f"{GAMMA_BASE}/{endpoint_path.lstrip('/')}"
    headers = {"User-Agent": "telegram-bot-stock2/2.12", "Accept": "application/json"}

    # Prioritize aiurl and create360 nodes
    nodes = list(TWOMD_SEARCH_ENDPOINTS)
    # Put create360 right after aiurl if present
    if "https://create360.ai" in nodes and nodes[1] != "https://create360.ai":
        nodes.remove("https://create360.ai")
        nodes.insert(1, "https://create360.ai")

    for base_2md in nodes:
        try:
            proxy_url = f"{base_2md.rstrip('/')}/{target_url}"
            resp = requests.get(proxy_url, headers=headers, timeout=timeout)
            if resp.status_code == 200 and resp.text:
                parsed = _parse_2md_content(resp.text)
                if parsed:
                    return parsed
        except Exception as e:
            logger.debug(f"2MD node {base_2md} failed for {target_url}: {e}")
            continue

    logger.warning(f"All 2MD nodes failed to fetch Polymarket API: {endpoint_path}")
    return None


def make_progress_bar(pct: float, width: int = 8) -> str:
    """Render a text-based percentage progress bar (e.g. [████░░░░] 45.0%)."""
    if pct < 0:
        pct = 0.0
    elif pct > 1:
        pct = 1.0
    filled = int(round(pct * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def format_usd(val: float) -> str:
    """Format USD numbers into readable abbreviations (e.g. $1.35M, $450.2K)."""
    if not val or val <= 0:
        return "$0"
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.0f}"


def _sanitize_market(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse raw market dictionary from Polymarket into standard format."""
    question = (m.get("question") or "").strip()
    if not question:
        return None

    # Parse outcomes
    raw_outcomes = m.get("outcomes") or "[]"
    if isinstance(raw_outcomes, str):
        try:
            outcomes = json.loads(raw_outcomes)
        except Exception:
            outcomes = ["Yes", "No"]
    else:
        outcomes = raw_outcomes

    # Parse outcome prices
    raw_prices = m.get("outcomePrices") or "[]"
    if isinstance(raw_prices, str):
        try:
            prices_str = json.loads(raw_prices)
            prices = [float(p) for p in prices_str]
        except Exception:
            prices = []
    elif isinstance(raw_prices, list):
        prices = [float(p) for p in raw_prices if p is not None]
    else:
        prices = []

    # Parse volume and liquidity
    vol_24h = float(m.get("volume24hr", 0) or 0)
    vol_total = float(m.get("volumeNum", 0) or m.get("volume", 0) or 0)
    liquidity = float(m.get("liquidityNum", 0) or m.get("liquidity", 0) or 0)

    slug = m.get("slug") or ""
    url = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"

    # Format outcomes with probabilities
    outcome_details = []
    for i, name in enumerate(outcomes):
        price = prices[i] if i < len(prices) else 0.0
        pct = price * 100
        bar = make_progress_bar(price, width=8)
        outcome_details.append({
            "name": name,
            "price": price,
            "probability_pct": f"{pct:.1f}%",
            "bar": bar
        })

    end_date = m.get("endDate") or m.get("endDateIso") or ""
    if "T" in end_date:
        end_date = end_date.split("T")[0]

    return {
        "question": question,
        "slug": slug,
        "url": url,
        "outcomes": outcome_details,
        "volume_24h": vol_24h,
        "volume_24h_str": format_usd(vol_24h),
        "volume_total": vol_total,
        "volume_total_str": format_usd(vol_total),
        "liquidity": liquidity,
        "liquidity_str": format_usd(liquidity),
        "end_date": end_date,
        "description": (m.get("description") or "")[:200]
    }


def fetch_polymarket_markets(
    keyword: str = "",
    limit: int = 6,
    filter_sports: bool = True
) -> List[Dict[str, Any]]:
    """Fetch active Polymarket prediction markets matching keyword or top macro events.

    Protected by TTLCache and SingleFlight.
    """
    clean_kw = keyword.strip().lower()
    # ``top`` is a UI alias for the unfiltered high-volume market list.
    if clean_kw in {"top", "熱門", "熱門市場", "global", "global hot"}:
        clean_kw = ""
    cache_key = f"pm:{clean_kw}:{limit}:{filter_sports}"
    cached = _pm_cache.get(cache_key)
    if cached is not None:
        return cached

    def _do_fetch():
        results = []
        seen_questions = set()

        # Check if keyword maps to a specific tag via direct or substring match
        tag_slug = KEYWORD_TAG_MAP.get(clean_kw)
        if not tag_slug and clean_kw:
            for kw_key, tag_val in KEYWORD_TAG_MAP.items():
                if kw_key in clean_kw:
                    tag_slug = tag_val
                    break

        # 1. If tag matched, query tag events
        if tag_slug:
            events_data = _fetch_polymarket_api(f"events?tag_slug={tag_slug}&limit=10&closed=false")
            if isinstance(events_data, list):
                for ev in events_data:
                    for m in ev.get("markets", []):
                        parsed = _sanitize_market(m)
                        if parsed and parsed["question"] not in seen_questions:
                            if filter_sports and any(re.search(pat, parsed["question"], re.IGNORECASE) for pat in SPORTS_PATTERNS):
                                continue
                            seen_questions.add(parsed["question"])
                            results.append(parsed)

        # 2. Query top volume markets from Gamma /markets (if needed or for general scan)
        if not tag_slug or len(results) < limit:
            markets_data = _fetch_polymarket_api("markets?limit=100&active=true&closed=false&order=volume24hr&ascending=false")
            if isinstance(markets_data, list):
                for m in markets_data:
                    parsed = _sanitize_market(m)
                    if not parsed:
                        continue
                    if filter_sports and any(re.search(pat, parsed["question"], re.IGNORECASE) for pat in SPORTS_PATTERNS):
                        continue

                    q_text = f"{parsed['question']} {parsed['description']}".lower()

                    # Filter relevance
                    if clean_kw and not tag_slug:
                        if clean_kw not in q_text:
                            continue
                    elif tag_slug:
                        if tag_slug not in q_text:
                            continue

                    if parsed["question"] not in seen_questions:
                        seen_questions.add(parsed["question"])
                        results.append(parsed)

        # 3. If query was empty and results too small, fetch additional macro tags
        if not clean_kw and len(results) < limit:
            for fallback_tag in ["fed", "economy", "business", "ai"]:
                evs = _fetch_polymarket_api(f"events?tag_slug={fallback_tag}&limit=5&closed=false")
                if isinstance(evs, list):
                    for ev in evs:
                        for m in ev.get("markets", []):
                            parsed = _sanitize_market(m)
                            if parsed and parsed["question"] not in seen_questions:
                                if filter_sports and any(
                                    re.search(pat, parsed["question"], re.IGNORECASE)
                                    for pat in SPORTS_PATTERNS
                                ):
                                    continue
                                seen_questions.add(parsed["question"])
                                results.append(parsed)

        # Sort by 24h volume descending
        results.sort(key=lambda x: x["volume_24h"], reverse=True)
        final_list = results[:limit]
        _pm_cache.set(cache_key, final_list)
        return final_list

    return _pm_singleflight.run(cache_key, _do_fetch)


def format_polymarket_markdown(markets: List[Dict[str, Any]], title: str = "") -> str:
    """Format markets into standard Markdown suitable for Telegram messages."""
    if not markets:
        return "🔮 **Polymarket 預測市場情報**\n\n查無相關活躍預測市場。請嘗試其他關鍵字（例如：`fed`, `降息`, `recession`, `trump`, `ai`, `crypto`）。"

    header = title if title else "🔮 **Polymarket 預測市場前瞻情報**"
    lines = [header, ""]

    for i, m in enumerate(markets, 1):
        q = m["question"]
        vol24 = m["volume_24h_str"]
        liq = m["liquidity_str"]
        end_d = m["end_date"]
        url = m["url"]

        lines.append(f"*{i}. {q}*")

        # Format outcomes
        for o in m["outcomes"][:3]:
            lines.append(f"  • {o['name']}: `{o['bar']}` **{o['probability_pct']}**")

        lines.append(f"  💰 24h成交: `{vol24}` | 💧 流動性: `{liq}`" + (f" | 📅 結算: `{end_d}`" if end_d else ""))
        lines.append(f"  🔗 [查看合約]({url})")
        lines.append("")

    lines.append("⚠️ *免責聲明：Polymarket 預測機率反映全球鏈上資本即時定價，僅供總經情緒與市場共識參考，非投資建議。*")
    return "\n".join(lines)


@tool
def get_polymarket_predictions(keyword_or_topic: str = "", limit: int = 5) -> Dict[str, Any]:
    """
    Fetches real-time crowd probability pricing, 24-hour volume, and market expectations from Polymarket prediction markets.
    Use this tool when users ask:
    - What is the market probability of Fed interest rate cuts/hikes? (e.g. '聯準會降息機率', 'Polymarket 降息')
    - Macroeconomic event odds (e.g. US recession, inflation, tariffs, debt ceiling).
    - Political/geopolitical forecasts (e.g. US elections, presidential actions, trade policies).
    - Corporate/tech catalysts (e.g. OpenAI IPO, TikTok ban, crypto ETF approvals).
    - General Polymarket hot predictions or market sentiment.
    """
    logger.info(f"=== [Tool] get_polymarket_predictions called with topic: {keyword_or_topic} ===")
    markets = fetch_polymarket_markets(keyword=keyword_or_topic, limit=limit)
    markdown_text = format_polymarket_markdown(
        markets,
        title=f"🔮 **Polymarket 預測市場：{keyword_or_topic or '全球熱門'}**"
    )

    return {
        "keyword": keyword_or_topic,
        "count": len(markets),
        "markets": markets,
        "formatted_summary": markdown_text
    }


@tool
def get_polymarket_macro_sentiment() -> Dict[str, Any]:
    """
    Fetches the highest-volume global macroeconomic, interest rate, and financial policy prediction markets on Polymarket.
    Returns forward-looking crowd probability distributions for Fed rate moves, recession risks, and major financial policies.
    """
    logger.info("=== [Tool] get_polymarket_macro_sentiment called ===")
    markets = fetch_polymarket_markets(keyword="fed", limit=4)
    recession_markets = fetch_polymarket_markets(keyword="economy", limit=3)

    combined = []
    seen = set()
    for m in markets + recession_markets:
        if m["question"] not in seen:
            seen.add(m["question"])
            combined.append(m)

    combined.sort(key=lambda x: x["volume_24h"], reverse=True)
    summary = format_polymarket_markdown(combined[:6], title="🔮 **Polymarket 全球總經與利率前瞻定價**")

    return {
        "macro_markets_count": len(combined[:6]),
        "markets": combined[:6],
        "formatted_summary": summary
    }
