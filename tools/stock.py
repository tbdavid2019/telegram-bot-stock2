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
import glob
import json
import re
from tools.news import fetch_2md_news

_TWSE_REGISTRY = {}
_TPEX_REGISTRY = {}
_NAME_TO_CODE = {}
_REGISTRY_INITIALIZED = False

def _init_tw_registry():
    global _TWSE_REGISTRY, _TPEX_REGISTRY, _NAME_TO_CODE, _REGISTRY_INITIALIZED
    if _REGISTRY_INITIALIZED:
        return
    _REGISTRY_INITIALIZED = True
    
    # Common high-frequency Taiwan company names
    common_names = {
        "儒鴻": "1476.TW", "台積電": "2330.TW", "鴻海": "2317.TW", "聯發科": "2454.TW",
        "聯電": "2303.TW", "長榮": "2603.TW", "陽明": "2609.TW", "萬海": "2615.TW",
        "廣達": "2382.TW", "緯創": "3231.TW", "技嘉": "2376.TW", "微星": "2377.TW",
        "華碩": "2357.TW", "大立光": "3008.TW", "欣興": "3037.TW", "富邦金": "2881.TW",
        "國泰金": "2882.TW", "中信金": "2891.TW", "兆豐金": "2886.TW", "玉山金": "2884.TW",
        "鈊象": "3293.TWO", "元太": "8069.TWO", "譜瑞": "4966.TWO", "信驊": "5274.TWO",
        "力旺": "3529.TWO", "環球晶": "6488.TWO", "群聯": "8299.TWO", "中光電": "5371.TWO",
        "穩懋": "3105.TWO", "雙鴻": "3324.TWO", "弘塑": "3131.TWO", "家登": "3680.TWO"
    }
    _NAME_TO_CODE.update(common_names)
    
    # Load from institutional cache if present
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(base_dir, "data", "cache", "institutional")
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
                        _NAME_TO_CODE[info["name"].strip()] = f"{c}.TW"
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
                        _NAME_TO_CODE[info["name"].strip()] = f"{c}.TWO"
        except Exception:
            pass

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
    "臉書": "META"
}

def resolve_ticker(company_or_query: str) -> str:
    """Resolve company name or ticker to standardized ticker symbol."""
    if not company_or_query:
        return ""
    _init_tw_registry()
    query = company_or_query.strip()
    upper_query = query.upper()
    
    if upper_query in KNOWN_TICKER_MAP:
        return KNOWN_TICKER_MAP[upper_query]
    
    clean_query = upper_query.replace("NASDAQ:", "").replace("NYSE:", "").replace("TWSE:", "").replace("TPEX:", "")
    if clean_query in KNOWN_TICKER_MAP:
        return KNOWN_TICKER_MAP[clean_query]

    # Check direct Chinese name or substring in Taiwan name registry
    if query in _NAME_TO_CODE:
        return _NAME_TO_CODE[query]
    for name, ticker in _NAME_TO_CODE.items():
        if len(name) >= 2 and (name == query or query in name or name in query):
            return ticker

    # If already has Taiwan or foreign market suffix (e.g. 1476.TW, 3293.TWO, 0700.HK)
    if re.match(r"^\d{4,6}\.(TW|TWO|HK|SS|SZ)$", upper_query):
        return upper_query

    # Extract 4-6 digit Taiwan stock code if embedded in query (e.g. "1476 儒鴻" or "1476")
    m = re.search(r"\b(\d{4,6}[A-Z]?)\b", upper_query)
    if m:
        c = m.group(1)
        if c in _TPEX_REGISTRY:
            return f"{c}.TWO"
        return f"{c}.TW"

    # US Ticker pattern (1-5 capital letters like NVDA, AAPL, SPCX)
    if re.match(r"^[A-Z]{1,5}$", upper_query):
        return upper_query

    # Fallback to 2MD search for unmapped company names
    try:
        results = fetch_2md_news(f"{company_or_query} stock ticker 股票代碼", limit=3)
        for item in results:
            title = item.get("title", "")
            desc = item.get("description", "")
            tw_match = re.search(r"\b(\d{4,6})\.(TW|TWO)\b", title, re.I) or re.search(r"\b(\d{4,6})\.(TW|TWO)\b", desc, re.I)
            if tw_match:
                return f"{tw_match.group(1)}.{tw_match.group(2).upper()}"
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
            clean_c = ticker.replace(".TW", "").replace(".TWO", "").strip()
            tw_name = _TWSE_REGISTRY.get(clean_c) or _TPEX_REGISTRY.get(clean_c) or _NAME_TO_CODE.get(ticker)
            eng_name = info.get("longName") or info.get("shortName") or ticker
            display_name = f"{tw_name} ({eng_name})" if tw_name and eng_name != ticker else (tw_name or eng_name)
            company_profile = {
                "name": display_name,
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
        
        clean_c = ticker.replace(".TW", "").replace(".TWO", "").strip()
        tw_name = _TWSE_REGISTRY.get(clean_c) or _TPEX_REGISTRY.get(clean_c)
        c_name = info.get('longName') or info.get('shortName') or 'N/A'
        display_name = f"{tw_name} ({c_name})" if tw_name and c_name != 'N/A' else (tw_name or c_name)

        revenue_growth = info.get('revenueGrowth', 'N/A')
        if revenue_growth is not None and revenue_growth != 'N/A':
            revenue_growth = round(revenue_growth * 100, 2)
        
        return {
            "stock": ticker,
            "company_info": {
                "name": display_name,
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
