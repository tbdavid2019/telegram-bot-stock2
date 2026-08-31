import io
import re
import time
import logging
import requests
import pandas as pd
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

TW_STOCKER_BASE_URL = "https://raw.githubusercontent.com/voidful/tw_stocker/main/data"
_tw_cache = {}

def clean_tw_ticker(ticker: str) -> str:
    """Extract pure stock code from ticker (e.g. 2330.TW -> 2330)."""
    match = re.search(r'(\d{4,6})', ticker)
    if match:
        return match.group(1)
    return ticker.replace(".TW", "").replace(".TWO", "").strip()

def fetch_tw_stocker_df(ticker: str) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV historical dataframe from voidful/tw_stocker dataset on GitHub.
    Uses 5-minute in-memory cache.
    """
    code = clean_tw_ticker(ticker)
    now = time.time()
    
    if code in _tw_cache and (now - _tw_cache[code]["time"] < 300):
        return _tw_cache[code]["df"].copy()

    url = f"{TW_STOCKER_BASE_URL}/{code}.csv"
    try:
        headers = {"User-Agent": "telegram-bot-stock2/tw_stocker"}
        resp = requests.get(url, headers=headers, timeout=6.0)
        if resp.status_code != 200:
            logger.warning(f"tw_stocker: {code}.csv not found (status {resp.status_code})")
            return None

        # Parse CSV
        df = pd.read_csv(io.StringIO(resp.text))
        if df.empty:
            return None

        # Check date column
        date_col = None
        for col in ["Date", "Datetime", "date", "datetime"]:
            if col in df.columns:
                date_col = col
                break
        
        if not date_col:
            logger.warning(f"tw_stocker: No date column in {code}.csv")
            return None

        df[date_col] = pd.to_datetime(df[date_col], errors='coerce', utc=True)
        df = df.dropna(subset=[date_col]).sort_values(by=date_col)
        
        # If intraday 5-min data, resample to daily OHLCV
        if "Datetime" in df.columns or "datetime" in df.columns or len(df) > 1000:
            df.set_index(date_col, inplace=True)
            # Ensure required numeric columns
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Resample to Daily
            daily_df = df.resample('1D').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna(subset=['Close'])
            
            if 'Adj Close' not in daily_df.columns:
                daily_df['Adj Close'] = daily_df['Close']
            
            df_final = daily_df
        else:
            df.set_index(date_col, inplace=True)
            for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            if 'Adj Close' not in df.columns and 'Close' in df.columns:
                df['Adj Close'] = df['Close']
            df_final = df

        if not df_final.empty:
            _tw_cache[code] = {"time": now, "df": df_final}
            logger.info(f"Successfully loaded {len(df_final)} daily rows for {code} from tw_stocker.")
            return df_final.copy()

    except Exception as e:
        logger.warning(f"Error fetching from tw_stocker for {code}: {e}")

    return None
