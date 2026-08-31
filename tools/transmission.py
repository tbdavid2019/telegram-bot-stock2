import re
import time
import logging
import requests
from typing import Dict, List, Optional, Any

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn):
        fn.invoke = lambda args: fn(**args) if isinstance(args, dict) else fn(args)
        return fn

logger = logging.getLogger(__name__)

DEEPEAR_LATEST_URL = "https://deepear.vercel.app/latest.json"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# In-memory cache for DeepEar Lite
_deepear_cache = {"time": 0, "data": []}

def fetch_deepear_lite_signals() -> List[Dict[str, Any]]:
    """
    Fetch the newest financial transmission-chain signals from DeepEar Lite.
    Uses 5-minute cache.
    """
    now = time.time()
    if _deepear_cache["data"] and (now - _deepear_cache["time"] < 300):
        return _deepear_cache["data"]

    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(DEEPEAR_LATEST_URL, headers=headers, timeout=8.0)
        if resp.status_code == 200:
            data = resp.json()
            signals = data.get("signals", [])
            _deepear_cache["time"] = now
            _deepear_cache["data"] = signals
            logger.info(f"Successfully fetched {len(signals)} signals from DeepEar Lite.")
            return signals
    except Exception as e:
        logger.warning(f"DeepEar Lite fetch failed: {e}")

    return _deepear_cache.get("data", [])

@tool
def analyze_market_transmission_chain(topic_or_event: str) -> Dict[str, Any]:
    """
    Analyzes the financial logic transmission chain for a given macroeconomic event, policy change, industry shock, or geopolitical event.
    Returns the multi-tier causal impact (Macro -> Industry 1st Order -> Company/Stock 2nd Order -> Benefited & Impacted Tickers) and active signals from DeepEar.
    ALWAYS use this tool when users ask:
    - '分析 [事件] 對市場/台股/美股的影響'
    - '降息/升息/地緣政治的傳導鏈為何'
    - '某產業異動/原物料暴漲暴跌的因果關係'
    """
    logger.info(f"=== [Tool] analyze_market_transmission_chain called for: {topic_or_event}")
    signals = fetch_deepear_lite_signals()
    
    # Search for related signals in DeepEar
    matched_signals = []
    query_clean = topic_or_event.lower().strip()
    keywords = re.findall(r'[\w\u4e00-\u9fff]+', query_clean)
    
    for s in signals:
        title = s.get("title", "")
        summary = s.get("summary", "")
        chain_text = str(s.get("transmission_chain", ""))
        full_text = f"{title} {summary} {chain_text}".lower()
        
        if any(kw in full_text for kw in keywords if len(kw) >= 2):
            matched_signals.append(s)

    result = {
        "query": topic_or_event,
        "matched_deepear_signals": matched_signals,
        "all_active_signals_summary": [
            {"title": s.get("title"), "category": s.get("category", "市場熱點")}
            for s in signals[:5]
        ],
        "guidelines": (
            "請根據查詢事件，構建完整的【三級金融邏輯傳導鏈 (Transmission Chain)】：\n"
            "1. 🌟 一級直接影響 (Direct Impact: 匯率、利率、原物料、直接供需)\n"
            "2. 🔄 二級產業鏈傳導 (Industry Transmission: 成本轉嫁、庫存、產能利用率)\n"
            "3. 🎯 三級受惠與受害標的 (Benefited vs Impacted Stocks: 具體台股/美股代號如 2330.TW, NVDA, 2603.TW)\n"
            "4. ⚖️ 邏輯證偽條件 (Falsification Criteria: 什麼指標或數據出現時此邏輯失效)\n"
            "5. 📊 請在回覆中繪製標準 Mermaid 流程圖 (語法如: ```mermaid\nflowchart LR\nA[\"事件\"] --> B[\"影響\"]\n```)"
        )
    }
    return result
