import io
import time
import logging
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from typing import Dict, List, Optional, Any

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

logger = logging.getLogger(__name__)

US_FDDK_V25_URL = "https://raw.githubusercontent.com/voidful/us_fddk/main/artifacts/paper_v25_state.json"
US_FDDK_STATUS_URL = "https://raw.githubusercontent.com/voidful/us_fddk/main/artifacts/v25_live_update_status.json"

_fddk_cache = {}

def fetch_us_fddk_paper_state() -> Optional[Dict[str, Any]]:
    """Fetch live paper trading state and asset allocation from voidful/us_fddk."""
    now = time.time()
    if "paper_state" in _fddk_cache and (now - _fddk_cache["paper_state"]["time"] < 600):
        return _fddk_cache["paper_state"]["data"]

    try:
        headers = {"User-Agent": "telegram-bot-stock2/us_fddk"}
        resp = requests.get(US_FDDK_V25_URL, headers=headers, timeout=6.0)
        if resp.status_code == 200:
            data = resp.json()
            _fddk_cache["paper_state"] = {"time": now, "data": data}
            return data
    except Exception as e:
        logger.warning(f"Failed to fetch us_fddk paper state: {e}")

    return None

def compute_fama_french_factors(ticker: str, period: str = "1y") -> Dict[str, Any]:
    """
    Computes Fama-French multi-factor risk attribution & alpha for a ticker:
    - Market Factor (Mkt-RF): SPY excess returns over SHY
    - Size Factor (SMB): Small Minus Big (IWM - SPY)
    - Value Factor (HML): High Minus Low (IWD - IWF)
    - Momentum Factor (UMD): Up Minus Down (MTUM - SPY)
    Uses OLS regression to decompose asset return and quantify Alpha.
    """
    ticker_clean = ticker.upper().strip()
    proxies = [ticker_clean, "SPY", "SHY", "IWM", "IWD", "IWF", "MTUM"]
    
    try:
        data = yf.download(proxies, period=period, progress=False)["Close"]
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        
        # Check if target ticker in data
        if ticker_clean not in data.columns or data[ticker_clean].dropna().empty:
            return {"ticker": ticker_clean, "error": f"無法獲取 {ticker_clean} 的歷史報酬數據"}
        
        # Calculate daily percentage returns
        rets = data.pct_change().dropna()
        if len(rets) < 60:
            return {"ticker": ticker_clean, "error": "交易日數不足 60 天，無法進行穩健的因子回歸"}

        # Construct Factor Returns
        R_i = rets[ticker_clean]
        R_f = rets["SHY"] if "SHY" in rets.columns else 0.0
        
        y = R_i - R_f
        Mkt_RF = rets["SPY"] - R_f
        SMB = rets["IWM"] - rets["SPY"]
        HML = rets["IWD"] - rets["IWF"]
        UMD = rets["MTUM"] - rets["SPY"]

        # Design Matrix X (with intercept for Alpha)
        X = np.column_stack([np.ones(len(y)), Mkt_RF, SMB, HML, UMD])
        
        # OLS regression: (X'X)^(-1) X'y
        beta, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
        
        alpha_daily, beta_mkt, beta_smb, beta_hml, beta_umd = beta
        alpha_annualized = alpha_daily * 252 * 100 # percentage
        
        # Calculate R-squared
        y_pred = X @ beta
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        ss_res = np.sum((y - y_pred) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0.0
        adj_r_squared = 1 - (1 - r_squared) * (len(y) - 1) / (len(y) - X.shape[1])

        # Style Diagnostics
        size_style = "大型股偏好 (Large-Cap Tilt)" if beta_smb < -0.15 else ("小型股偏好 (Small-Cap Tilt)" if beta_smb > 0.15 else "中性市值 (Size Neutral)")
        value_style = "價值型偏好 (Value Tilt)" if beta_hml > 0.15 else ("成長型偏好 (Growth Tilt)" if beta_hml < -0.15 else "估值中性 (Core Blend)")
        mom_style = "強動能驅動 (High Momentum)" if beta_umd > 0.15 else ("反轉/落後股 (Low/Reversal Momentum)" if beta_umd < -0.15 else "動能中性 (Momentum Neutral)")

        return {
            "ticker": ticker_clean,
            "period": period,
            "sample_days": len(y),
            "annualized_alpha_pct": round(float(alpha_annualized), 2),
            "beta_market": round(float(beta_mkt), 3),
            "beta_size_smb": round(float(beta_smb), 3),
            "beta_value_hml": round(float(beta_hml), 3),
            "beta_momentum_umd": round(float(beta_umd), 3),
            "r_squared": round(float(r_squared), 4),
            "adj_r_squared": round(float(adj_r_squared), 4),
            "style_profile": {
                "size": size_style,
                "value_growth": value_style,
                "momentum": mom_style
            },
            "source": "Fama-French Multi-Factor Model (Proxy: SPY/SHY/IWM/IWD/IWF/MTUM)"
        }

    except Exception as e:
        logger.error(f"Fama-French regression error for {ticker_clean}: {e}")
        return {"ticker": ticker_clean, "error": f"因子回歸計算異常: {str(e)}"}

@tool
def get_fama_french_factor_analysis(ticker: str) -> Dict[str, Any]:
    """
    Computes Fama-French multi-factor risk attribution (Market Beta, SMB Size, HML Value, UMD Momentum) and Annualized Alpha.
    Use this tool when users ask:
    - '分析 [股票] 的 Fama-French 多因子模型 / 因子曝險'
    - '[股票] 究竟是成長型還是價值型？大市值還是小市值？'
    - '[股票] 的超額報酬 Alpha 來源是什麼'
    """
    logger.info(f"=== [Tool] get_fama_french_factor_analysis called for: {ticker}")
    return compute_fama_french_factors(ticker)

@tool
def get_us_fddk_live_benchmarks() -> Dict[str, Any]:
    """
    Fetches the live paper trading and macro multi-asset benchmark portfolio state from voidful/us_fddk.
    Returns the latest v25 strategy (80% VUG / 20% GLD), SPY comparison, and allocation weights.
    Use this tool when users ask about 20-year ETF asset allocation research or live benchmark paper tracking.
    """
    logger.info("=== [Tool] get_us_fddk_live_benchmarks called")
    state = fetch_us_fddk_paper_state()
    if not state:
        return {"error": "暫時無法連接至 us_fddk live 基準倉庫"}

    holdings = state.get("holdings", {})
    return {
        "strategy": state.get("strategy", "v25 80% VUG／20% GLD"),
        "as_of": state.get("as_of"),
        "mode": state.get("mode"),
        "initial_cash": state.get("initial_cash"),
        "holdings": holdings,
        "total_costs": state.get("total_costs"),
        "transactions_count": len(state.get("transactions", [])),
        "source": "https://github.com/voidful/us_fddk"
    }
