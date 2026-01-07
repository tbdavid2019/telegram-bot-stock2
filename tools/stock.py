import yfinance as yf
import datetime as dt
import pandas as pd
from typing import Dict
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD
from ta.volume import volume_weighted_average_price
from langchain_core.tools import tool
import asyncio

@tool
def get_stock_prices(ticker: str) -> Dict:
    """Fetches historical stock price data and technical indicators for a given ticker."""
    print(f"=== [Tool] get_stock_prices called with ticker: {ticker}")
    try:
        # Wrap the blocking yf.download call in a thread
        # Note: yf.download is not async, so we likely run it directly here unless we want to use run_in_executor in the caller.
        # But since this is a tool called by LangChain/LangGraph, it might be running in a threadpool anyway.
        # For simplicity in this tool definition (which is sync-style for LangChain tools often), we keep it as is 
        # but ensure proper error handling. 
        # However, for the bot handlers we will use run_in_executor.
        
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
        if len(df.columns) > 0 and isinstance(df.columns[0], tuple) and len(df.columns[0]) > 1:
            df.columns = [i[0] for i in df.columns]
        data.reset_index(inplace=True)
        data['Date'] = data['Date'].astype(str)

        # Technical Indicators
        indicators = {}

        # RSI
        if len(df) > 14:
            rsi_series = RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
            indicators["RSI"] = round(rsi_series, 2)

            # Stochastic Oscillator
            sto_series = StochasticOscillator(df['High'], df['Low'], df['Close'], window=14).stoch().iloc[-1]
            indicators["Stochastic_Oscillator"] = round(sto_series, 2)

            # MACD
            macd = MACD(df['Close'])
            macd_series = macd.macd().iloc[-1]
            macd_signal_series = macd.macd_signal().iloc[-1]
            indicators["MACD"] = round(macd_series, 2)
            indicators["MACD_Signal"] = round(macd_signal_series, 2)

            # VWAP
            vwap_series = volume_weighted_average_price(
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                volume=df['Volume'],
            ).iloc[-1]
            indicators["VWAP"] = round(vwap_series, 2)
        else:
            indicators["Note"] = "Not enough data for technical indicators (need > 14 days)"

        return {
            "stock": ticker,
            "latest_close_price": round(df['Close'].iloc[-1], 2),
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
