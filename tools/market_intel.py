"""Public-market intelligence tools backed by the 2MD endpoint cluster.

2MD is used as a reader/search layer, so the parsers intentionally preserve
source URLs and excerpts. A layout change on a source site should result in a
partial, clearly labelled answer instead of invented transactions.

Enhanced with:
- Multi-tier TTLCache for SERP searches and URL markdown reader
- SingleFlight concurrency coalescing to prevent thundering herds
- Optimized 8.5s/12.0s timeouts and stale-while-revalidate disaster recovery
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import requests
import yfinance as yf

from config import TWOMD_SEARCH_ENDPOINTS
from tools.cache_util import TTLCache, SingleFlight

try:
    from langchain_core.tools import tool
except ImportError:  # pragma: no cover
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn


logger = logging.getLogger(__name__)
REQUEST_HEADERS = {"User-Agent": "telegram-bot-stock2/2.11", "Accept": "application/json"}
READER_HEADERS = {"User-Agent": "telegram-bot-stock2/2.11", "Accept": "text/plain"}

# --- Caches & SingleFlight for Market Intelligence ---
_intel_search_cache = TTLCache(default_ttl=900.0, max_size=500)   # 15 min for 2MD SERP queries
_intel_reader_cache = TTLCache(default_ttl=3600.0, max_size=1000) # 1 hour for URL markdown content
_holdings_cache = TTLCache(default_ttl=7200.0, max_size=200)      # 2 hours for 13F filings
_insider_cache = TTLCache(default_ttl=1800.0, max_size=200)       # 30 min for Form 4 filings
_squeeze_cache = TTLCache(default_ttl=1200.0, max_size=200)       # 20 min for short squeeze
_sentiment_cache = TTLCache(default_ttl=600.0, max_size=200)      # 10 min for retail sentiment
_intel_singleflight = SingleFlight()


def _twomd_search(query: str, limit: int = 8) -> List[Dict[str, str]]:
    """Search each 2MD node until a useful result set is returned.
    
    Protected by 15-minute TTL Cache and SingleFlight deduplication.
    """
    cache_key = f"{query.strip().lower()}_{limit}"
    cached = _intel_search_cache.get(cache_key)
    if cached is not None:
        return cached

    def _do_search():
        for base_url in TWOMD_SEARCH_ENDPOINTS:
            try:
                # Optimized timeout from 10s to 8.5s
                response = requests.get(
                    f"{base_url.rstrip('/')}/search",
                    params={"q": query},
                    headers=REQUEST_HEADERS,
                    timeout=8.5,
                )
                if response.status_code != 200:
                    continue
                payload = response.json()
                items = payload.get("data", payload.get("results", [])) if isinstance(payload, dict) else []
                if not isinstance(items, list):
                    continue
                results = []
                for item in items[:limit]:
                    if not isinstance(item, dict):
                        continue
                    url = str(item.get("url") or item.get("link") or "").strip()
                    title = str(item.get("title") or "").strip()
                    description = str(item.get("description") or item.get("snippet") or "").strip()
                    if title or description:
                        results.append({"title": title, "url": url, "description": description})
                if results:
                    _intel_search_cache.set(cache_key, results, ttl=900.0)
                    return results
            except Exception as exc:
                logger.warning("2MD search failed on %s: %s", base_url, exc)

        stale = _intel_search_cache.get_stale(cache_key)
        return stale if stale is not None else []

    try:
        return _intel_singleflight.run(f"intel_s:{cache_key}", _do_search)
    except Exception as exc:
        logger.warning("SingleFlight intel search failed for '%s': %s", query, exc)
        stale = _intel_search_cache.get_stale(cache_key)
        return stale if stale is not None else []


def _twomd_read(url: str) -> str:
    """Read a source URL through 2MD nodes, returning plain text.
    
    Protected by 1-hour TTL Cache and SingleFlight deduplication.
    """
    if not url:
        return ""
    cached = _intel_reader_cache.get(url)
    if cached is not None:
        return cached

    def _do_read():
        encoded_url = quote(url, safe=":/?=&%#")
        for base_url in TWOMD_SEARCH_ENDPOINTS:
            try:
                # Optimized timeout to 12.0s
                response = requests.get(
                    f"{base_url.rstrip('/')}/{encoded_url}",
                    headers=READER_HEADERS,
                    timeout=12.0,
                )
                if response.status_code == 200 and response.text.strip():
                    text = response.text.strip()
                    _intel_reader_cache.set(url, text, ttl=3600.0)
                    return text
            except Exception as exc:
                logger.warning("2MD reader failed on %s for %s: %s", base_url, url, exc)

        stale = _intel_reader_cache.get_stale(url)
        return stale if stale is not None else ""

    try:
        return _intel_singleflight.run(f"intel_r:{url}", _do_read)
    except Exception as exc:
        logger.warning("SingleFlight intel read failed for '%s': %s", url, exc)
        stale = _intel_reader_cache.get_stale(url)
        return stale if stale is not None else ""


def _source_excerpts(results: Iterable[Dict[str, str]], max_chars: int = 7000) -> str:
    parts: List[str] = []
    for result in results:
        text = " — ".join(part for part in (result.get("title"), result.get("description")) if part)
        if text:
            parts.append(text)
        if result.get("url"):
            parts.append(f"來源：{result['url']}")
    return "\n".join(parts)[:max_chars]


def _transaction_lines(text: str, limit: int = 12) -> List[str]:
    action_words = re.compile(r"\b(buy|bought|purchase|purchased|sell|sold|sale|added|reduced|held|option|exercise|acquisition)\b", re.I)
    lines = []
    for line in re.split(r"[\r\n]+", text):
        compact = re.sub(r"\s+", " ", line).strip()
        if compact and action_words.search(compact) and len(compact) > 12:
            lines.append(compact[:400])
        if len(lines) >= limit:
            break
    return lines


def _classify_insider(line: str) -> str:
    lowered = line.lower()
    if re.search(r"\b(p|open market|purchase|buy|bought)\b", lowered):
        return "open_market_buy"
    if re.search(r"\b(s|sale|sell|sold)\b", lowered):
        return "open_market_sell"
    if re.search(r"\b(m|option|exercise|grant)\b", lowered):
        return "option_or_grant"
    return "unclassified"


def _parse_insider_line(line: str) -> Dict[str, Any]:
    """Extract optional Form 4 fields without guessing missing values."""
    date_match = re.search(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}/\d{1,2}/20\d{2})\b", line)
    shares_match = re.search(
        r"(?:shares?|qty|quantity)\s*[:=]?\s*([\d,]+)|\b([\d,]+)\s+(?:shares?|qty|quantity)\b",
        line,
        re.I,
    )
    price_match = re.search(r"(?:price|@)\s*[:=]?\s*\$?([\d,.]+)|\$([\d,.]+)", line, re.I)
    officer_match = re.search(
        r"\b(?:CEO|CFO|COO|Director|Chair(?:man|woman)?|Officer)\s*[:\-]?\s*"
        r"([A-Z][\w .'-]{2,}?)(?=\s+(?:purchase|purchased|sale|sold|buy|bought|sell|\d)|$)",
        line,
        re.I,
    )
    return {
        "date": date_match.group(1) if date_match else None,
        "officer": officer_match.group(1).strip() if officer_match else None,
        "shares": int(next(value for value in shares_match.groups() if value).replace(",", "")) if shares_match else None,
        "price": next((float(value.replace(",", "")) for value in price_match.groups() if value), None) if price_match else None,
        "transaction_type": _classify_insider(line),
        "excerpt": line,
    }


def _get_superinvestor_holdings_impl(ticker: str) -> Dict[str, Any]:
    results = _twomd_search(f"{ticker} Dataroma 13F superinvestor holdings buys sells", limit=8)
    reader_text = ""
    for result in results[:3]:
        if result.get("url"):
            reader_text += "\n" + _twomd_read(result["url"])
    lines = _transaction_lines(reader_text or _source_excerpts(results))
    changes = []
    for line in lines:
        action_match = re.search(r"\b(bought|buy|added|sold|sell|reduced|held)\b", line, re.I)
        weight_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:of portfolio|weight)?", line, re.I)
        changes.append({
            "action": action_match.group(1).lower() if action_match else "unclassified",
            "portfolio_weight_percent": float(weight_match.group(1)) if weight_match else None,
            "excerpt": line,
        })
    res = {
        "stock": ticker,
        "source": "2MD search/reader → Dataroma/WhaleWisdom public pages",
        "results_found": len(results),
        "portfolio_changes": changes,
        "search_results": results[:6],
        "evidence_excerpt": (reader_text or _source_excerpts(results))[:5000],
        "note": "13F 申報通常按季公布且有延遲；找不到結構化交易時會保留原始摘錄，不推測基金名稱或持倉權重。",
    }
    _holdings_cache.set(ticker, res, ttl=7200.0)
    return res


@tool
def get_superinvestor_holdings(ticker: str) -> Dict[str, Any]:
    """Track superinvestor 13F mentions and quarterly portfolio changes.
    Cached for 2 hours with SingleFlight thundering-herd prevention.
    """
    ticker = ticker.strip().upper()
    cached = _holdings_cache.get(ticker)
    if cached is not None:
        return cached

    try:
        return _intel_singleflight.run(f"holdings:{ticker}", _get_superinvestor_holdings_impl, ticker)
    except Exception as exc:
        logger.warning("get_superinvestor_holdings failed for %s: %s", ticker, exc)
        stale = _holdings_cache.get_stale(ticker)
        if stale is not None:
            return stale
        return {
            "stock": ticker,
            "error": f"13F 持倉檢索失敗：{str(exc)}",
            "portfolio_changes": []
        }


def _get_insider_trading_impl(ticker: str) -> Dict[str, Any]:
    results = _twomd_search(f"{ticker} SEC Form 4 insider trading OpenInsider Finviz", limit=8)
    reader_text = ""
    for result in results[:3]:
        if result.get("url"):
            reader_text += "\n" + _twomd_read(result["url"])
    lines = _transaction_lines(reader_text or _source_excerpts(results))
    transactions = [_parse_insider_line(line) for line in lines]
    res = {
        "stock": ticker,
        "source": "2MD search/reader → OpenInsider/Finviz/SEC public pages",
        "transactions": transactions,
        "search_results": results[:6],
        "evidence_excerpt": (reader_text or _source_excerpts(results))[:5000],
        "interpretation": "open_market_buy/sell 與 option_or_grant 分開標示；摘錄不足時不會把期權行使誤判成自由買入。",
    }
    _insider_cache.set(ticker, res, ttl=1800.0)
    return res


@tool
def get_insider_trading(ticker: str) -> Dict[str, Any]:
    """Extract recent Form 4 insider activity from OpenInsider/Finviz via 2MD.
    Cached for 30 minutes with SingleFlight thundering-herd prevention.
    """
    ticker = ticker.strip().upper()
    cached = _insider_cache.get(ticker)
    if cached is not None:
        return cached

    try:
        return _intel_singleflight.run(f"insider:{ticker}", _get_insider_trading_impl, ticker)
    except Exception as exc:
        logger.warning("get_insider_trading failed for %s: %s", ticker, exc)
        stale = _insider_cache.get_stale(ticker)
        if stale is not None:
            return stale
        return {
            "stock": ticker,
            "error": f"內部人交易檢索失敗：{str(exc)}",
            "transactions": []
        }


def _first_info_value(info: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        value = info.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _get_short_squeeze_analysis_impl(ticker: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        logger.warning("Unable to read short-interest data for %s: %s", ticker, exc)
    short_float = _first_info_value(info, ("shortPercentOfFloat",))
    if short_float is not None and short_float > 1:
        short_float /= 100
    short_ratio = _first_info_value(info, ("shortRatio",))
    shares_short = _first_info_value(info, ("sharesShort",))
    float_shares = _first_info_value(info, ("floatShares",))
    borrow_results = _twomd_search(f"{ticker} borrow fee rate cost to borrow short squeeze", limit=6)
    evidence = _source_excerpts(borrow_results)
    fee_matches = re.findall(r"(?:borrow fee|cost to borrow|CTB)[^\d%]{0,30}(\d+(?:\.\d+)?)\s*%", evidence, re.I)
    fee_rates = [float(value) for value in fee_matches]
    risk_points = 0
    if short_float is not None and short_float >= 0.20:
        risk_points += 1
    if short_ratio is not None and short_ratio >= 5:
        risk_points += 1
    if fee_rates and max(fee_rates) >= 10:
        risk_points += 1
    risk = "高" if risk_points >= 2 else "中" if risk_points == 1 else "低或資料不足"
    risk_factors = [factor for factor in (
        "高空頭比率" if short_float is not None and short_float >= 0.20 else None,
        "高 days-to-cover" if short_ratio is not None and short_ratio >= 5 else None,
        "2MD 摘錄含高借券費率" if fee_rates and max(fee_rates) >= 10 else None,
    ) if factor]
    res = {
        "stock": ticker,
        "short_percent_of_float": short_float,
        "days_to_cover_short_ratio": short_ratio,
        "shares_short": shares_short,
        "float_shares": float_shares,
        "borrow_fee_rates_percent": fee_rates,
        "borrow_fee_evidence": evidence[:4000],
        "squeeze_risk": risk,
        "risk_factors": risk_factors,
        "note": "yfinance 欄位與公開網頁資料可能延遲或缺漏；借券費率因券商、庫存和時間而異，不是可成交報價。",
    }
    _squeeze_cache.set(ticker, res, ttl=1200.0)
    return res


@tool
def get_short_squeeze_analysis(ticker: str) -> Dict[str, Any]:
    """Combine yfinance short-interest fields with 2MD borrow-fee evidence.
    Cached for 20 minutes with SingleFlight thundering-herd prevention.
    """
    ticker = ticker.strip().upper()
    cached = _squeeze_cache.get(ticker)
    if cached is not None:
        return cached

    try:
        return _intel_singleflight.run(f"squeeze:{ticker}", _get_short_squeeze_analysis_impl, ticker)
    except Exception as exc:
        logger.warning("get_short_squeeze_analysis failed for %s: %s", ticker, exc)
        stale = _squeeze_cache.get_stale(ticker)
        if stale is not None:
            return stale
        return {
            "stock": ticker,
            "error": f"軋空指標檢索失敗：{str(exc)}",
            "squeeze_risk": "資料不足"
        }


def _sentiment_score(text: str) -> int:
    positive = ("bullish", "buy", "calls", "moon", "squeeze", "undervalued", "看多", "上漲")
    negative = ("bearish", "sell", "puts", "dump", "overvalued", "short", "看空", "下跌")
    lowered = text.lower()
    return sum(lowered.count(word.lower()) for word in positive) - sum(lowered.count(word.lower()) for word in negative)


def _get_retail_sentiment_impl(ticker: str) -> Dict[str, Any]:
    searches = {
        "reddit_wsb": f"{ticker} site:reddit.com/r/wallstreetbets",
        "stocktwits": f"{ticker} site:stocktwits.com sentiment",
    }
    channels: Dict[str, Any] = {}
    all_text = []
    for channel, query in searches.items():
        results = _twomd_search(query, limit=5)
        excerpts = _source_excerpts(results, max_chars=2500)
        reader_text = "\n".join(_twomd_read(result["url"]) for result in results[:2] if result.get("url"))
        evidence = reader_text or excerpts
        score = _sentiment_score(evidence)
        channels[channel] = {
            "mention_count": len(results),
            "sentiment_score": score,
            "tone": "bullish" if score > 0 else "bearish" if score < 0 else "mixed_or_unclear",
            "mentions": results,
            "reader_excerpt": evidence[:2500],
        }
        all_text.append(evidence)
    total_score = sum(channel["sentiment_score"] for channel in channels.values())
    res = {
        "stock": ticker,
        "channels": channels,
        "overall_tone": "bullish" if total_score > 0 else "bearish" if total_score < 0 else "mixed_or_unclear",
        "catalyst_excerpts": "\n".join(text for text in all_text if text)[:5000],
        "method": "2MD SERP 摘要的關鍵字訊號；不是統計代表性民調，也不代表投資建議。",
    }
    _sentiment_cache.set(ticker, res, ttl=600.0)
    return res


@tool
def get_retail_sentiment(ticker: str) -> Dict[str, Any]:
    """Scan Reddit WSB and StockTwits mentions through 2MD search.
    Cached for 10 minutes with SingleFlight thundering-herd prevention.
    """
    ticker = ticker.strip().upper()
    cached = _sentiment_cache.get(ticker)
    if cached is not None:
        return cached

    try:
        return _intel_singleflight.run(f"sentiment:{ticker}", _get_retail_sentiment_impl, ticker)
    except Exception as exc:
        logger.warning("get_retail_sentiment failed for %s: %s", ticker, exc)
        stale = _sentiment_cache.get_stale(ticker)
        if stale is not None:
            return stale
        return {
            "stock": ticker,
            "error": f"社群情緒檢索失敗：{str(exc)}",
            "overall_tone": "mixed_or_unclear"
        }


__all__ = [
    "get_superinvestor_holdings",
    "get_insider_trading",
    "get_short_squeeze_analysis",
    "get_retail_sentiment",
]
