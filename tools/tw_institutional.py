import os
import re
import json
import ssl
import logging
import datetime as dt
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional, Tuple

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache", "institutional")
os.makedirs(CACHE_DIR, exist_ok=True)

SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}


def _clean_number(val: Any) -> float:
    """Parse comma-separated number string to float (in shares or percentage)."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("+", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _clean_ticker(ticker: str) -> str:
    """Extract standard Taiwan 4-6 digit stock code."""
    t = ticker.strip().upper()
    m = re.search(r"(\d{4,6})", t)
    return m.group(1) if m else t


def _fetch_url_json(url: str, timeout: int = 5) -> Optional[Dict[str, Any]]:
    """Helper to fetch JSON payload with SSL and headers."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")
            return json.loads(content)
    except Exception as e:
        logger.debug("Failed fetching %s: %s", url, e)
        return None


def fetch_twse_t86(date_str: str) -> Dict[str, Dict[str, Any]]:
    """Fetch TWSE (上市) T86 Institutional Trading for a specific date (YYYYMMDD)."""
    cache_path = os.path.join(CACHE_DIR, f"{date_str}_twse_t86.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALLBUT0999&response=json"
    data = _fetch_url_json(url)
    if not data or data.get("stat") != "OK" or not data.get("data"):
        return {}

    result = {}
    for r in data["data"]:
        if len(r) < 19:
            continue
        code = r[0].strip()
        name = r[1].strip()
        foreign_no_dealer = _clean_number(r[4])
        foreign_dealer = _clean_number(r[7])
        foreign_total = foreign_no_dealer + foreign_dealer
        trust = _clean_number(r[10])
        dealer_self = _clean_number(r[14])
        dealer_hedge = _clean_number(r[17])
        dealer_total = _clean_number(r[11])
        total = _clean_number(r[18])

        result[code] = {
            "market": "TWSE",
            "name": name,
            "foreign_lots": round(foreign_total / 1000.0, 1),
            "trust_lots": round(trust / 1000.0, 1),
            "dealer_lots": round(dealer_total / 1000.0, 1),
            "dealer_self_lots": round(dealer_self / 1000.0, 1),
            "dealer_hedge_lots": round(dealer_hedge / 1000.0, 1),
            "total_lots": round(total / 1000.0, 1),
        }

    if result:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed saving cache %s: %s", cache_path, e)

    return result


def fetch_twse_qfiis(date_str: str) -> Dict[str, Dict[str, Any]]:
    """Fetch TWSE (上市) MI_QFIIS foreign ownership stats for date (YYYYMMDD)."""
    cache_path = os.path.join(CACHE_DIR, f"{date_str}_twse_qfiis.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    url = f"https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={date_str}&selectType=ALLBUT0999&response=json"
    data = _fetch_url_json(url)
    if not data or data.get("stat") != "OK" or not data.get("data"):
        return {}

    result = {}
    for r in data["data"]:
        if len(r) < 8:
            continue
        code = r[0].strip()
        hold_shares = _clean_number(r[5])
        ratio = _clean_number(r[7])
        result[code] = {
            "foreign_hold_lots": round(hold_shares / 1000.0, 1),
            "foreign_ratio": ratio
        }

    if result:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed saving cache %s: %s", cache_path, e)

    return result


def fetch_tpex_daily(date_str: str) -> Dict[str, Dict[str, Any]]:
    """Fetch TPEX (上櫃) 3itrade Institutional Trading for date (YYYYMMDD)."""
    cache_path = os.path.join(CACHE_DIR, f"{date_str}_tpex.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    url = f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={date_str}&response=json"
    data = _fetch_url_json(url)
    if not data:
        return {}

    tables = data.get("tables", [])
    if not tables or not tables[0].get("data"):
        return {}

    result = {}
    for r in tables[0]["data"]:
        if len(r) < 24:
            continue
        code = r[0].strip()
        name = r[1].strip()
        foreign_total = _clean_number(r[10])
        trust = _clean_number(r[13])
        dealer_self = _clean_number(r[16])
        dealer_hedge = _clean_number(r[19])
        dealer_total = _clean_number(r[22])
        total = _clean_number(r[23])

        result[code] = {
            "market": "TPEX",
            "name": name,
            "foreign_lots": round(foreign_total / 1000.0, 1),
            "trust_lots": round(trust / 1000.0, 1),
            "dealer_lots": round(dealer_total / 1000.0, 1),
            "dealer_self_lots": round(dealer_self / 1000.0, 1),
            "dealer_hedge_lots": round(dealer_hedge / 1000.0, 1),
            "total_lots": round(total / 1000.0, 1),
        }

    if result:
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception as e:
            logger.warning("Failed saving cache %s: %s", cache_path, e)

    return result


def _get_recent_trading_dates(max_days: int = 15) -> List[str]:
    """Generate candidate trading dates (YYYYMMDD), skipping weekends."""
    dates = []
    curr = dt.date.today()
    count = 0
    while len(dates) < max_days and count < 30:
        if curr.weekday() < 5:  # Monday to Friday
            dates.append(curr.strftime("%Y%m%d"))
        curr -= dt.timedelta(days=1)
        count += 1
    return dates


def _fetch_single_day_data(d: str, code: str) -> Optional[Dict[str, Any]]:
    """Fetch institutional data for a single date for given code."""
    # Check TWSE first
    twse_data = fetch_twse_t86(d)
    if code in twse_data:
        item = dict(twse_data[code])
        item["date"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        qfiis = fetch_twse_qfiis(d)
        if code in qfiis:
            item["foreign_ratio"] = qfiis[code].get("foreign_ratio")
            item["foreign_hold_lots"] = qfiis[code].get("foreign_hold_lots")
        return item
    
    # Check TPEX
    tpex_data = fetch_tpex_daily(d)
    if code in tpex_data:
        item = dict(tpex_data[code])
        item["date"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        return item

    return None


def get_tw_stock_institutional_history(ticker: str, target_trading_days: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch up to `target_trading_days` of institutional investor data for a Taiwan stock concurrently.
    """
    code = _clean_ticker(ticker)
    candidate_dates = _get_recent_trading_dates(max_days=target_trading_days + 4)
    
    history = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_fetch_single_day_data, d, code): d for d in candidate_dates}
        for future in futures:
            try:
                res = future.result()
                if res:
                    history.append(res)
            except Exception as e:
                logger.debug("Error fetching institutional data: %s", e)

    # Sort chronological: oldest to newest
    history.sort(key=lambda x: x["date"])
    return history[-target_trading_days:]


def _calculate_streak(values: List[float]) -> Tuple[int, str]:
    """Calculate consecutive buy or sell streak from the most recent day backwards."""
    if not values:
        return (0, "neutral")
    latest = values[-1]
    if latest > 0:
        direction = "buy"
    elif latest < 0:
        direction = "sell"
    else:
        return (0, "neutral")

    streak = 0
    for v in reversed(values):
        if direction == "buy" and v > 0:
            streak += 1
        elif direction == "sell" and v < 0:
            streak += 1
        else:
            break
    return (streak, direction)


@tool
def get_tw_institutional_analysis(ticker: str) -> Dict[str, Any]:
    """
    Fetch Taiwan Stock Exchange (TWSE/TPEX) institutional investors trading breakdown,
    foreign and trust net buy/sell lots, consecutive streak (連買/連賣天數), and 5d accumulation.
    """
    code = _clean_ticker(ticker)
    history = get_tw_stock_institutional_history(code, target_trading_days=10)
    if not history:
        return {
            "stock": ticker,
            "code": code,
            "error": f"查無台股代碼 {code} 之三大法人買賣超資料（可能為非交易日、代碼錯誤或假日尚未開盤）。"
        }

    latest = history[-1]
    name = latest.get("name", code)
    market = latest.get("market", "TWSE")

    foreign_history = [h.get("foreign_lots", 0.0) for h in history]
    trust_history = [h.get("trust_lots", 0.0) for h in history]
    dealer_history = [h.get("dealer_lots", 0.0) for h in history]
    total_history = [h.get("total_lots", 0.0) for h in history]

    # Streaks
    f_streak, f_dir = _calculate_streak(foreign_history)
    t_streak, t_dir = _calculate_streak(trust_history)

    # 5-day accumulations
    f_5d = round(sum(foreign_history[-5:]), 1)
    t_5d = round(sum(trust_history[-5:]), 1)
    d_5d = round(sum(dealer_history[-5:]), 1)
    total_5d = round(sum(total_history[-5:]), 1)

    # Smart Sentiment Logic
    sentiment_tag = "中性觀望"
    if t_streak >= 3 and f_streak >= 2 and f_dir == "buy" and t_dir == "buy":
        sentiment_tag = "🔥 土洋聯手強勢作多 (外資投信同步連買)"
    elif t_streak >= 3 and t_dir == "buy":
        sentiment_tag = "🚀 投信強勢認養波段 (投信連續買超)"
    elif f_streak >= 3 and f_dir == "buy":
        sentiment_tag = "🌐 外資波段回補推升 (外資連續買超)"
    elif f_dir == "buy" and t_dir == "sell":
        sentiment_tag = "⚡ 土洋對作 (外資買進、投信調節)"
    elif f_dir == "sell" and t_dir == "buy":
        sentiment_tag = "⚡ 土洋對作 (投信護盤、外資提款)"
    elif f_dir == "sell" and t_dir == "sell" and (f_streak >= 3 or t_streak >= 3):
        sentiment_tag = "🌧️ 法人同步撤出偏空 (外資投信連賣)"

    recent_table = []
    for h in history[-5:]:
        recent_table.append({
            "date": h.get("date"),
            "foreign_lots": h.get("foreign_lots", 0),
            "trust_lots": h.get("trust_lots", 0),
            "dealer_lots": h.get("dealer_lots", 0),
            "total_lots": h.get("total_lots", 0)
        })

    return {
        "stock": f"{code} {name}",
        "market": market,
        "latest_date": latest.get("date"),
        "latest_day": {
            "foreign_lots": latest.get("foreign_lots"),
            "trust_lots": latest.get("trust_lots"),
            "dealer_lots": latest.get("dealer_lots"),
            "dealer_self_lots": latest.get("dealer_self_lots"),
            "dealer_hedge_lots": latest.get("dealer_hedge_lots"),
            "total_lots": latest.get("total_lots"),
            "foreign_ratio": latest.get("foreign_ratio")
        },
        "streaks": {
            "foreign": f"連 {f_streak} {'買' if f_dir == 'buy' else '賣'}" if f_streak > 0 else "持平",
            "trust": f"連 {t_streak} {'買' if t_dir == 'buy' else '賣'}" if t_streak > 0 else "持平"
        },
        "accumulated_5d": {
            "foreign_lots": f_5d,
            "trust_lots": t_5d,
            "dealer_lots": d_5d,
            "total_lots": total_5d
        },
        "sentiment_evaluation": sentiment_tag,
        "recent_5_days_history": recent_table
    }
