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

@tool
def get_stock_prices(ticker: str) -> Dict:
    """Fetches historical stock price data and technical indicators for a given ticker."""
    print(f"=== [Tool] get_stock_prices called with ticker: {ticker}")
    try:
        data = yf.download(
            ticker,
            start=dt.datetime.now() - dt.timedelta(weeks=13),
            end=dt.datetime.now(),
            interval='1d',
            progress=False
        )
        if data.empty:
            return {"error": f"No data found for {ticker}"}
        df = data.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        elif len(df.columns) > 0 and isinstance(df.columns[0], tuple):
            df.columns = [i[0] for i in df.columns]
            
        data.reset_index(inplace=True)
        data['Date'] = data['Date'].astype(str)

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
        return {
            "stock": ticker,
            "latest_close_price": latest_price,
            "indicators": indicators
        }
    except Exception as e:
        return {"error": f"無法獲取技術分析數據: {str(e)}"}

@tool
def get_financial_metrics(ticker: str) -> Dict:
    """Fetches key financial ratios for a given ticker."""
    print(f"=== [Tool] get_financial_metrics called with ticker: {ticker}")
    try:
        stock = yf.Ticker(ticker)
        # Accessing info is blocking
        info = stock.info
        
        revenue_growth = info.get('revenueGrowth', 'N/A')
        if revenue_growth is not None and revenue_growth != 'N/A':
            revenue_growth = round(revenue_growth * 100, 2)
        
        return {
            "stock": ticker,
            "company_info": {
                "name": info.get('longName', 'N/A'),
                "sector": info.get('sector', 'N/A'),
                "industry": info.get('industry', 'N/A'),
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
