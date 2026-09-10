import yfinance as yf
import datetime as dt
import pandas as pd
from typing import Dict
try:
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.trend import MACD
    from ta.volume import volume_weighted_average_price
    HAS_TA = True
except ImportError:
    HAS_TA = False

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

import os
import sys
import glob
import json
import re
import threading
from zoneinfo import ZoneInfo
from tools.news import fetch_2md_news
from tools.cache_util import SingleFlight

_TWSE_REGISTRY = {}
_TPEX_REGISTRY = {}
_TW_NAME_TO_CODE = {}

_HK_STOCKS = {}
_HK_CODE_MAP = {}
_HK_NAME_TO_CODE = {}

_US_STOCKS = {}
_US_NAME_TO_TICKER = {}

_JPX_STOCKS = {}
_JPX_NAME_TO_TICKER = {}

_CN_STOCKS = {}
_CN_NAME_TO_TICKER = {}

_LSE_STOCKS = {}
_LSE_NAME_TO_TICKER = {}

_EURONEXT_STOCKS = {}
_EURONEXT_NAME_TO_TICKER = {}

_REGISTRIES_INITIALIZED = False
_LAST_DAILY_REFRESH_DATE = None
_DAILY_REFRESH_SINGLEFLIGHT = SingleFlight()
_DAILY_REFRESH_STALE_STATUS = {}


def _init_registries():
    global _TWSE_REGISTRY, _TPEX_REGISTRY, _TW_NAME_TO_CODE
    global _HK_STOCKS, _HK_CODE_MAP, _HK_NAME_TO_CODE
    global _US_STOCKS, _US_NAME_TO_TICKER
    global _JPX_STOCKS, _JPX_NAME_TO_TICKER
    global _CN_STOCKS, _CN_NAME_TO_TICKER
    global _LSE_STOCKS, _LSE_NAME_TO_TICKER
    global _EURONEXT_STOCKS, _EURONEXT_NAME_TO_TICKER
    global _REGISTRIES_INITIALIZED

    if _REGISTRIES_INITIALIZED:
        return
    _REGISTRIES_INITIALIZED = True

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base_dir, "data")

    # 1. Tier 1: Taiwan Registry (TWSE & TPEx)
    tw_file = os.path.join(data_dir, "tw_stock_registry.json")
    if os.path.exists(tw_file):
        try:
            with open(tw_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
                stocks = reg.get("stocks", {})
                for code, info in stocks.items():
                    c = code.strip().upper()
                    market = info.get("market", "TWSE")
                    name = info.get("name", "").strip()
                    suffix = info.get("suffix", ".TW" if market == "TWSE" else ".TWO")
                    if market == "TWSE":
                        _TWSE_REGISTRY[c] = name
                    else:
                        _TPEX_REGISTRY[c] = name
                    if name:
                        _TW_NAME_TO_CODE[name] = f"{c}{suffix}"
        except Exception:
            pass

    # Tier 2: Dynamic Taiwan daily institutional cache
    cache_dir = os.path.join(data_dir, "cache", "institutional")
    twse_files = sorted(glob.glob(os.path.join(cache_dir, "*_twse_t86.json")), reverse=True)
    tpex_files = sorted(glob.glob(os.path.join(cache_dir, "*_tpex.json")), reverse=True)
    if twse_files:
        try:
            with open(twse_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
                for code, info in data.items():
                    c = code.strip().upper()
                    _TWSE_REGISTRY[c] = info.get("name", "")
                    if "name" in info and info["name"]:
                        _TW_NAME_TO_CODE[info["name"].strip()] = f"{c}.TW"
        except Exception:
            pass
    if tpex_files:
        try:
            with open(tpex_files[0], "r", encoding="utf-8") as f:
                data = json.load(f)
                for code, info in data.items():
                    c = code.strip().upper()
                    _TPEX_REGISTRY[c] = info.get("name", "")
                    if "name" in info and info["name"]:
                        _TW_NAME_TO_CODE[info["name"].strip()] = f"{c}.TWO"
        except Exception:
            pass

    # 2. Hong Kong Registry (HKEX ListOfSecurities)
    hk_file = os.path.join(data_dir, "hk_stock_registry.json")
    if os.path.exists(hk_file):
        try:
            with open(hk_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
                stocks = reg.get("stocks", {})
                for code, info in stocks.items():
                    _HK_STOCKS[code] = info
                    ticker = info.get("ticker", "")
                    int_code = info.get("int_code", "")
                    if ticker:
                        _HK_CODE_MAP[code] = ticker
                        if int_code:
                            _HK_CODE_MAP[int_code] = ticker
                            _HK_CODE_MAP[f"{int(int_code):04d}"] = ticker
                aliases = reg.get("aliases", {})
                for name, ticker in aliases.items():
                    _HK_NAME_TO_CODE[name] = ticker
        except Exception:
            pass

    # 3. US Registry (SEC EDGAR + High-Frequency Aliases)
    us_file = os.path.join(data_dir, "us_stock_registry.json")
    if os.path.exists(us_file):
        try:
            with open(us_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
                _US_STOCKS.update(reg.get("stocks", {}))
                aliases = reg.get("aliases", {})
                for name, ticker in aliases.items():
                    _US_NAME_TO_TICKER[name] = ticker
        except Exception:
            pass

    # 4. Japan Registry (JPX Tokyo Stock Exchange)
    jpx_file = os.path.join(data_dir, "jpx_stock_registry.json")
    if os.path.exists(jpx_file):
        try:
            with open(jpx_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
                _JPX_STOCKS.update(reg.get("stocks", {}))
                aliases = reg.get("aliases", {})
                for name, ticker in aliases.items():
                    _JPX_NAME_TO_TICKER[name] = ticker
        except Exception:
            pass

    # 5. China A-Shares Registry (SSE & SZSE)
    cn_file = os.path.join(data_dir, "cn_stock_registry.json")
    if os.path.exists(cn_file):
        try:
            with open(cn_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
                _CN_STOCKS.update(reg.get("stocks", {}))
                aliases = reg.get("aliases", {})
                for name, ticker in aliases.items():
                    _CN_NAME_TO_TICKER[name] = ticker
        except Exception:
            pass

    # 6. UK Registry (LSE London Stock Exchange)
    lse_file = os.path.join(data_dir, "lse_stock_registry.json")
    if os.path.exists(lse_file):
        try:
            with open(lse_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
                _LSE_STOCKS.update(reg.get("stocks", {}))
                aliases = reg.get("aliases", {})
                for name, ticker in aliases.items():
                    _LSE_NAME_TO_TICKER[name] = ticker
        except Exception:
            pass

    # 7. European Registry (Euronext Paris, Amsterdam, Brussels, Lisbon, Dublin, Milan, Oslo)
    euronext_file = os.path.join(data_dir, "euronext_stock_registry.json")
    if os.path.exists(euronext_file):
        try:
            with open(euronext_file, "r", encoding="utf-8") as f:
                reg = json.load(f)
                _EURONEXT_STOCKS.update(reg.get("stocks", {}))
                aliases = reg.get("aliases", {})
                for name, ticker in aliases.items():
                    _EURONEXT_NAME_TO_TICKER[name] = ticker
        except Exception:
            pass


def _check_and_trigger_daily_refresh():
    """Lazy on-demand daily refresh gated at midnight (00:00 Asia/Taipei).
    
    When the first request of the day arrives after 00:00 Asia/Taipei,
    SingleFlight coalesces concurrent queries, triggers an asynchronous
    background refresh, and falls back gracefully to stale local cache if any
    source fails (stale: True).
    """
    global _LAST_DAILY_REFRESH_DATE
    now_taipei = dt.datetime.now(ZoneInfo("Asia/Taipei"))
    today_str = now_taipei.strftime("%Y-%m-%d")

    if _LAST_DAILY_REFRESH_DATE == today_str:
        return

    def _worker():
        global _LAST_DAILY_REFRESH_DATE
        print(f"🔄 [Registry] First request of the day at {now_taipei.strftime('%Y-%m-%d %H:%M:%S')} (Asia/Taipei). Triggering daily global registry update...")
        try:
            import subprocess
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script_path = os.path.join(base_dir, "scripts", "update_stock_registries.py")
            if os.path.exists(script_path):
                ret = subprocess.run([sys.executable, script_path], capture_output=True, text=True, timeout=90)
                if ret.returncode != 0:
                    print(f"⚠️ [Registry] Daily refresh warning: {ret.stderr.strip()[:200]}")
                else:
                    print(f"✅ [Registry] Daily global registry refresh successful.")
        except Exception as e:
            print(f"⚠️ [Registry] Daily refresh failed with error: {e}. Preserving last valid cache (stale: True).")

        _LAST_DAILY_REFRESH_DATE = today_str

    threading.Thread(target=lambda: _DAILY_REFRESH_SINGLEFLIGHT.run(today_str, _worker), daemon=True).start()


_init_tw_registry = _init_registries


KNOWN_TICKER_MAP = {
    "SPACEX": "SPCX",
    "SPACE X": "SPCX",
    "SPCX": "SPCX",
    "太空探索": "SPCX",
    "TSMC": "2330.TW",
    "台積電": "2330.TW",
    "聯發科": "2454.TW",
    "鴻海": "2317.TW",
    "聯電": "2303.TW",
    "輝達": "NVDA",
    "特斯拉": "TSLA",
    "蘋果": "AAPL",
    "微軟": "MSFT",
    "亞馬遜": "AMZN",
    "谷歌": "GOOGL",
    "臉書": "META",
    "騰訊": "0700.HK",
    "騰訊控股": "0700.HK",
    "阿里巴巴": "9988.HK",
    "美團": "3690.HK",
    "小米": "1810.HK",
    "小米集團": "1810.HK",
    "比亞迪": "1211.HK",
    "匯豐控股": "0005.HK",
    "匯豐": "0005.HK"
}


def resolve_ticker(company_or_query: str) -> str:
    """Resolve company name or ticker across Taiwan, Hong Kong, US, Japan, and China stock markets."""
    if not company_or_query:
        return ""
    _init_registries()
    _check_and_trigger_daily_refresh()
    query = company_or_query.strip()
    upper_query = query.upper()

    # 1. Check known explicit overrides
    if upper_query in KNOWN_TICKER_MAP:
        return KNOWN_TICKER_MAP[upper_query]

    clean_query = (
        upper_query.replace("NASDAQ:", "")
        .replace("NYSE:", "")
        .replace("TWSE:", "")
        .replace("TPEX:", "")
        .replace("HKEX:", "")
        .replace("JPX:", "")
        .replace("SSE:", "")
        .replace("SZSE:", "")
        .replace("LSE:", "")
        .replace("EURONEXT:", "")
        .replace("HK:", "")
        .replace("TW:", "")
        .replace("US:", "")
        .replace("JP:", "")
        .replace("CN:", "")
        .replace("UK:", "")
        .replace("EU:", "")
    )
    if clean_query in KNOWN_TICKER_MAP:
        return KNOWN_TICKER_MAP[clean_query]

    # 2. Direct exact matches for Chinese / Japanese / European names
    if query in _US_NAME_TO_TICKER:
        return _US_NAME_TO_TICKER[query]
    if upper_query in _US_NAME_TO_TICKER:
        return _US_NAME_TO_TICKER[upper_query]

    if query in _HK_NAME_TO_CODE:
        return _HK_NAME_TO_CODE[query]
    if upper_query in _HK_NAME_TO_CODE:
        return _HK_NAME_TO_CODE[upper_query]

    if query in _JPX_NAME_TO_TICKER:
        return _JPX_NAME_TO_TICKER[query]
    if upper_query in _JPX_NAME_TO_TICKER:
        return _JPX_NAME_TO_TICKER[upper_query]

    if query in _CN_NAME_TO_TICKER:
        return _CN_NAME_TO_TICKER[query]
    if upper_query in _CN_NAME_TO_TICKER:
        return _CN_NAME_TO_TICKER[upper_query]

    if query in _LSE_NAME_TO_TICKER:
        return _LSE_NAME_TO_TICKER[query]
    if upper_query in _LSE_NAME_TO_TICKER:
        return _LSE_NAME_TO_TICKER[upper_query]

    if query in _EURONEXT_NAME_TO_TICKER:
        return _EURONEXT_NAME_TO_TICKER[query]
    if upper_query in _EURONEXT_NAME_TO_TICKER:
        return _EURONEXT_NAME_TO_TICKER[upper_query]

    if query in _TW_NAME_TO_CODE:
        return _TW_NAME_TO_CODE[query]

    # 3. If already formatted with international market suffix
    if re.match(r"^([A-Z0-9]{1,10})\.(TW|TWO|HK|T|SS|SZ|L|PA|AS|BR|LS|IR|MI|OL)$", upper_query):
        return upper_query

    # 4. Explicit HK prefix/suffix pattern (e.g. "HK0700", "0700HK", "HK700")
    m_hk = re.search(r"\bHK(\d{3,5})\b", upper_query) or re.search(r"\b(\d{3,5})HK\b", upper_query)
    if m_hk:
        code_int = int(m_hk.group(1))
        return f"{code_int:04d}.HK"

    # Explicit JP prefix/suffix (e.g. "JP7203", "7203JP")
    m_jp = re.search(r"\bJP(\d{4})\b", upper_query) or re.search(r"\b(\d{4})JP\b", upper_query)
    if m_jp:
        return f"{m_jp.group(1)}.T"

    # 5. Numeric ticker resolution (Taiwan vs Hong Kong vs Japan vs China)
    m_num = re.search(r"\b(\d{3,6}[A-Z]?)\b", upper_query)
    if m_num:
        c = m_num.group(1)

        # 6 digits: China A-Shares (SSE / SZSE)
        if len(c) == 6 and c.isdigit():
            if c.startswith("60") or c.startswith("68"):
                return f"{c}.SS"
            if c.startswith("00") or c.startswith("30"):
                return f"{c}.SZ"
            if c in _CN_STOCKS:
                return _CN_STOCKS[c].get("ticker", f"{c}.SS")

        # Starts with '0' or is 5 digits:
        if c.startswith("0") or len(c) == 5:
            # Check Taiwan ETFs (0050, 0056, 00878, etc.)
            if c in _TWSE_REGISTRY:
                return f"{c}.TW"
            if c in _TPEX_REGISTRY:
                return f"{c}.TWO"
            # HK stock code (e.g. 00700 -> 0700.HK, 09988 -> 9988.HK)
            if c in _HK_CODE_MAP:
                return _HK_CODE_MAP[c]
            try:
                c_int = int(re.sub(r"\D", "", c))
                return f"{c_int:04d}.HK"
            except Exception:
                pass

        # 3-digit number (e.g. 700) -> HK stock
        if len(c) == 3 and c.isdigit():
            if c in _HK_CODE_MAP:
                return _HK_CODE_MAP[c]
            return f"{int(c):04d}.HK"

        # 4-digit number:
        # Prioritize Taiwan (e.g. 1476, 2330, 3293)
        if c in _TPEX_REGISTRY:
            return f"{c}.TWO"
        if c in _TWSE_REGISTRY:
            return f"{c}.TW"

        # If not listed in Taiwan, check HK (e.g. 9988, 3690, 1211, 9618)
        if c in _HK_CODE_MAP:
            return _HK_CODE_MAP[c]

        # If not in Taiwan or HK, check JPX (e.g. 7203, 6758, 9984)
        if c in _JPX_STOCKS:
            return f"{c}.T"

        # Default fallback for 4 digits is Taiwan
        return f"{c}.TW"

    # 6. US Ticker pattern (1-5 capital letters like NVDA, AAPL, SPCX)
    if re.match(r"^[A-Z]{1,5}$", upper_query):
        return upper_query

    # 7. Substring name matching across markets (Taiwan -> HK -> US -> JP -> CN)
    for name, ticker in _TW_NAME_TO_CODE.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    for name, ticker in _HK_NAME_TO_CODE.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    for name, ticker in _US_NAME_TO_TICKER.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    for name, ticker in _JPX_NAME_TO_TICKER.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    for name, ticker in _CN_NAME_TO_TICKER.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    for name, ticker in _LSE_NAME_TO_TICKER.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    for name, ticker in _EURONEXT_NAME_TO_TICKER.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    # 8. Fallback to 2MD web search for unmapped company names
    try:
        results = fetch_2md_news(f"{company_or_query} stock ticker 股票代碼", limit=3)
        for item in results:
            title = item.get("title", "")
            desc = item.get("description", "")
            m_suf = re.search(r"\b([A-Z0-9]{1,6})\.(TW|TWO|HK|T|SS|SZ|L|PA|AS|BR|LS|IR|MI|OL)\b", title, re.I) or re.search(r"\b([A-Z0-9]{1,6})\.(TW|TWO|HK|T|SS|SZ|L|PA|AS|BR|LS|IR|MI|OL)\b", desc, re.I)
            if m_suf:
                return f"{m_suf.group(1)}.{m_suf.group(2).upper()}"
            match = re.search(r"\(([A-Z]{1,5})\)", title) or re.search(r"\(([A-Z]{1,5})\)", desc)
            if match:
                return match.group(1)
            tw_code_match = re.search(r"\b(\d{4,6})\b", title) or re.search(r"\b(\d{4,6})\b", desc)
            if tw_code_match:
                code_cand = tw_code_match.group(1)
                if code_cand in _TPEX_REGISTRY:
                    return f"{code_cand}.TWO"
                return f"{code_cand}.TW"
    except Exception:
        pass
    return upper_query


def _get_market_and_display_name(ticker: str, info: dict) -> tuple:
    """Helper to determine official exchange market name and display name across 7 global markets."""
    clean_c = (
        ticker.replace(".TW", "")
        .replace(".TWO", "")
        .replace(".HK", "")
        .replace(".T", "")
        .replace(".SS", "")
        .replace(".SZ", "")
        .replace(".L", "")
        .replace(".PA", "")
        .replace(".AS", "")
        .replace(".BR", "")
        .replace(".LS", "")
        .replace(".IR", "")
        .replace(".MI", "")
        .replace(".OL", "")
        .strip()
    )

    tw_name = _TWSE_REGISTRY.get(clean_c) or _TPEX_REGISTRY.get(clean_c) or _TW_NAME_TO_CODE.get(ticker)
    hk_info = _HK_STOCKS.get(f"{int(clean_c):05d}") if (ticker.endswith(".HK") and clean_c.isdigit()) else None
    us_info = _US_STOCKS.get(ticker)
    jpx_info = _JPX_STOCKS.get(clean_c) if ticker.endswith(".T") else None
    cn_info = _CN_STOCKS.get(clean_c) if (ticker.endswith(".SS") or ticker.endswith(".SZ")) else None
    lse_info = _LSE_STOCKS.get(clean_c) if ticker.endswith(".L") else None

    euronext_venues = {
        ".PA": "Euronext Paris (泛歐巴黎交易所)",
        ".AS": "Euronext Amsterdam (泛歐阿姆斯特丹交易所)",
        ".BR": "Euronext Brussels (泛歐布魯塞爾交易所)",
        ".LS": "Euronext Lisbon (泛歐里斯本交易所)",
        ".IR": "Euronext Dublin (泛歐都柏林交易所)",
        ".MI": "Euronext Milan (泛歐米蘭交易所 / 義大利證交所)",
        ".OL": "Euronext Oslo (奧斯陸證券交易所)"
    }

    eng_name = info.get("longName") or info.get("shortName") or ticker

    if tw_name:
        market_name = "TWSE (台灣證券交易所)" if ticker.endswith(".TW") else "TPEx (證券櫃檯買賣中心)"
        display_name = f"{tw_name} ({eng_name})" if eng_name != ticker else tw_name
    elif hk_info:
        market_name = "HKEX (香港交易所)"
        c_name = hk_info.get("name", "")
        display_name = f"{c_name} ({eng_name})" if eng_name != ticker else c_name
    elif us_info:
        market_name = "US Market (NYSE/NASDAQ/AMEX)"
        display_name = us_info.get("name", ticker)
    elif jpx_info:
        market_name = "JPX (東京證券交易所)"
        j_name = jpx_info.get("name", "")
        display_name = f"{j_name} ({eng_name})" if eng_name != ticker else j_name
    elif cn_info:
        market_name = cn_info.get("market", "China A-Shares (SSE/SZSE)")
        c_name = cn_info.get("name", "")
        display_name = f"{c_name} ({eng_name})" if eng_name != ticker else c_name
    elif lse_info:
        market_name = "LSE (倫敦證券交易所)"
        l_name = lse_info.get("name", "")
        display_name = f"{l_name} ({eng_name})" if l_name and eng_name != l_name else (l_name or eng_name)
    elif ticker.endswith(".L"):
        market_name = "LSE (倫敦證券交易所)"
        display_name = eng_name
    elif any(ticker.endswith(suf) for suf in euronext_venues):
        suf = next(s for s in euronext_venues if ticker.endswith(s))
        market_name = euronext_venues[suf]
        display_name = eng_name
    else:
        market_name = "Global Market"
        display_name = eng_name

    return market_name, display_name


@tool
def get_stock_prices(ticker: str) -> Dict:
    """Fetches historical stock price data and technical indicators for a given ticker or company name."""
    ticker = resolve_ticker(ticker)
    print(f"=== [Tool] get_stock_prices called with ticker: {ticker}")
    try:
        data = yf.download(
            ticker,
            period="3mo",
            interval='1d',
            progress=False
        )
        if data.empty:
            # Fallback to tw_stocker for Taiwan stocks
            if ".TW" in ticker.upper() or ".TWO" in ticker.upper() or any(c.isdigit() for c in ticker):
                from tools.tw_stocker import fetch_tw_stocker_df
                tw_df = fetch_tw_stocker_df(ticker)
                if tw_df is not None and not tw_df.empty:
                    data = tw_df.tail(65).copy()
        if data.empty:
            return {"error": f"No data found for {ticker}"}
        df = data.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        elif len(df.columns) > 0 and isinstance(df.columns[0], tuple):
            df.columns = [i[0] for i in df.columns]
            
        data.reset_index(inplace=True)
        if 'Date' in data.columns:
            data['Date'] = data['Date'].astype(str)
        elif 'Datetime' in data.columns:
            data['Date'] = data['Datetime'].astype(str)

        # Ensure numeric series
        close_series = pd.to_numeric(df['Close'], errors='coerce').dropna()
        high_series = pd.to_numeric(df['High'], errors='coerce').dropna()
        low_series = pd.to_numeric(df['Low'], errors='coerce').dropna()
        volume_series = pd.to_numeric(df['Volume'], errors='coerce').dropna()

        # Technical Indicators
        indicators = {}

        if len(close_series) > 14:
            if HAS_TA:
                rsi_series = RSIIndicator(close_series, window=14).rsi().iloc[-1]
                sto_series = StochasticOscillator(high_series, low_series, close_series, window=14).stoch().iloc[-1]
                macd = MACD(close_series)
                macd_series = macd.macd().iloc[-1]
                macd_signal_series = macd.macd_signal().iloc[-1]
                vwap_series = volume_weighted_average_price(
                    high=high_series,
                    low=low_series,
                    close=close_series,
                    volume=volume_series,
                ).iloc[-1]
            else:
                # Pandas fallback calculations
                delta = close_series.diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / (loss + 1e-9)
                rsi_series = (100 - (100 / (1 + rs))).iloc[-1]

                low14 = low_series.rolling(14).min()
                high14 = high_series.rolling(14).max()
                sto_series = (100 * (close_series - low14) / ((high14 - low14) + 1e-9)).iloc[-1]

                ema12 = close_series.ewm(span=12, adjust=False).mean()
                ema26 = close_series.ewm(span=26, adjust=False).mean()
                macd_line = ema12 - ema26
                macd_signal = macd_line.ewm(span=9, adjust=False).mean()
                macd_series = macd_line.iloc[-1]
                macd_signal_series = macd_signal.iloc[-1]

                vwap_series = ((close_series * volume_series).cumsum() / (volume_series.cumsum() + 1e-9)).iloc[-1]

            indicators["RSI"] = round(float(rsi_series), 2)
            indicators["Stochastic_Oscillator"] = round(float(sto_series), 2)
            indicators["MACD"] = round(float(macd_series), 2)
            indicators["MACD_Signal"] = round(float(macd_signal_series), 2)
            indicators["VWAP"] = round(float(vwap_series), 2)
        else:
            indicators["Note"] = "Not enough data for technical indicators (need > 14 days)"

        latest_price = round(float(close_series.iloc[-1]), 2) if not close_series.empty else "N/A"

        # Attach company profile metadata so LLM always knows company's real identity & industry
        company_profile = {}
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            market_name, display_name = _get_market_and_display_name(ticker, info)
            company_profile = {
                "name": display_name,
                "market": market_name,
                "sector": info.get("sector") or "N/A",
                "industry": info.get("industry") or "N/A",
                "business_summary": (info.get("longBusinessSummary")[:300] + "...") if info.get("longBusinessSummary") else "N/A"
            }
        except Exception:
            pass

        return {
            "stock": ticker,
            "company_profile": company_profile,
            "latest_close_price": latest_price,
            "indicators": indicators
        }
    except Exception as e:
        return {"error": f"無法獲取技術分析數據: {str(e)}"}

@tool
def get_financial_metrics(ticker: str) -> Dict:
    """Fetches key financial ratios for a given ticker or company name."""
    ticker = resolve_ticker(ticker)
    print(f"=== [Tool] get_financial_metrics called with ticker: {ticker}")
    try:
        stock = yf.Ticker(ticker)
        # Accessing info is blocking
        info = stock.info or {}
        market_name, display_name = _get_market_and_display_name(ticker, info)

        revenue_growth = info.get('revenueGrowth', 'N/A')
        if revenue_growth is not None and revenue_growth != 'N/A':
            revenue_growth = round(revenue_growth * 100, 2)
        
        return {
            "stock": ticker,
            "company_info": {
                "name": display_name,
                "market": market_name,
                "sector": info.get('sector', 'N/A'),
                "industry": info.get('industry', 'N/A'),
                "business_summary": (info.get('longBusinessSummary')[:300] + "...") if info.get('longBusinessSummary') else 'N/A',
                "market_cap": info.get('marketCap', 'N/A'),
                "market_cap_billions": round(info.get('marketCap', 0) / 1e9, 2) if info.get('marketCap') else 'N/A'
            },
            "revenue_data": {
                "total_revenue": info.get('totalRevenue', 'N/A'),
                "revenue_growth": revenue_growth
            },
            "profitability_ratios": {
                "gross_profit_margin": info.get('grossMargins', 'N/A'),
                "operating_profit_margin": info.get('operatingMargins', 'N/A'),
                "net_profit_margin": info.get('profitMargins', 'N/A')
            },
            "financial_health": {
                "current_ratio": info.get('currentRatio', 'N/A'),
                "quick_ratio": info.get('quickRatio', 'N/A'),
                "debt_to_equity": info.get('debtToEquity', 'N/A')
            },
            "market_ratios": {
                "pe_ratio": info.get('trailingPE', 'N/A'),
                "forward_pe": info.get('forwardPE', 'N/A'),
                "price_to_book": info.get('priceToBook', 'N/A'),
                "dividend_yield": info.get('dividendYield', 'N/A')
            }
        }
    except Exception as e:
        return {"error": f"無法獲取財務指標數據: {str(e)}"}
