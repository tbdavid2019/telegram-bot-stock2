import os
import re
import json
import logging
from typing import TypedDict, Annotated, List, Dict
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

from config import (
    OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL,
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
    FALLBACK_LLM_API_KEY, FALLBACK_LLM_BASE_URL, FALLBACK_LLM_MODEL
)
from tools.stock import get_stock_prices, get_financial_metrics
from tools.stock_analysis import (
    get_sepa_analysis,
    get_dcf_valuation,
    get_earnings_briefing,
    get_correlation_analysis,
)
from tools.market_intel import (
    get_superinvestor_holdings,
    get_insider_trading,
    get_short_squeeze_analysis,
    get_retail_sentiment,
)
from tools.news import get_financial_news, search_financial_web, get_hot_news_flash
from tools.transmission import analyze_market_transmission_chain
from tools.us_fddk import get_fama_french_factor_analysis, get_us_fddk_live_benchmarks
from tools.tw_institutional import get_tw_institutional_analysis
from tools.wiki import publish_to_wiki

logger = logging.getLogger(__name__)

# --- State Definition ---
class State(TypedDict):
    messages: Annotated[list, add_messages]
    stock: str

# --- Main Agent Setup ---
main_agent_tools = [
    get_stock_prices,
    get_financial_metrics,
    get_financial_news,
    search_financial_web,
    get_hot_news_flash,
    analyze_market_transmission_chain,
    get_tw_institutional_analysis,
    get_fama_french_factor_analysis,
    get_us_fddk_live_benchmarks,
    get_sepa_analysis,
    get_dcf_valuation,
    get_earnings_briefing,
    get_correlation_analysis,
    get_superinvestor_holdings,
    get_insider_trading,
    get_short_squeeze_analysis,
    get_retail_sentiment,
    publish_to_wiki,
]

# Initialize Primary LLM (NEN / DeepSeek-v4-flash)
primary_llm = ChatOpenAI(
    model=LLM_MODEL,
    api_key=LLM_API_KEY or "dummy-key",
    base_url=LLM_BASE_URL,
    temperature=0.1,
    max_tokens=2048
)
primary_with_tools = primary_llm.bind_tools(main_agent_tools)

# Initialize Fallback LLM (Groq) if configured
if FALLBACK_LLM_API_KEY:
    fallback_llm = ChatOpenAI(
        model=FALLBACK_LLM_MODEL,
        api_key=FALLBACK_LLM_API_KEY,
        base_url=FALLBACK_LLM_BASE_URL,
        temperature=0.1,
        max_tokens=2048
    )
    fallback_with_tools = fallback_llm.bind_tools(main_agent_tools)
    main_llm_with_tools = primary_with_tools.with_fallbacks([fallback_with_tools])
    logger.info(f"Main agent initialized with Primary ({LLM_MODEL}) and Fallback ({FALLBACK_LLM_MODEL})")
else:
    main_llm_with_tools = primary_with_tools
    logger.info(f"Main agent initialized with Primary ({LLM_MODEL})")

# --- Memory Setup ---
# Initialize in-memory persistence for conversation history
valid_memory = MemorySaver()

# --- Main Agent Graph ---
class MainAgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]

def main_agent_node(state: MainAgentState):
    """Core node for the main agent."""
    messages = state["messages"]
    
    # Optional system prompt
    system_prompt = SystemMessage(content="""
You are DAVID888 stock assistant, a helpful, highly knowledgeable, and professional AI financial assistant.

You have access to dynamic real-time tools:
- `get_stock_prices`: Real-time stock prices & technical indicators (RSI, Stochastic, MACD, VWAP).
- `get_financial_metrics`: Key fundamental financial ratios (P/E, revenue growth, profit margins, debt-to-equity, current ratio).
- `get_financial_news`: Live ticker news from 2MD search and Yahoo/Google fallbacks.
- `get_hot_news_flash`: Real-time breaking financial headlines from 財聯社 (cls), 華爾街見聞 (wallstreetcn), and 雪球 (xueqiu).
- `analyze_market_transmission_chain`: Multi-tier financial logic transmission chain analysis (Macro -> Industry -> Benefited/Impacted Tickers) with DeepEar signals and Mermaid diagrams.
- `get_fama_french_factor_analysis`: Multi-factor risk attribution & Alpha estimation (Market Beta, SMB Size, HML Value, UMD Momentum, Adjusted R-squared).
- `get_us_fddk_live_benchmarks`: Live paper portfolio asset allocation & 20-year ETF research benchmarks from voidful/us_fddk.
- `search_financial_web`: 2MD live SERP search engine for company backgrounds, IPO status, ticker lookups, breaking news, and macroeconomic events.
- `get_sepa_analysis`: Mark Minervini 8-point Trend Template, Stage 2 status, pivot, stops, and VCP diagnostics.
- `get_dcf_valuation`: Five-year FCFF DCF with live `^TNX` risk-free rate, WACC, scenarios, and sensitivity matrix.
- `get_earnings_briefing`: Earnings date, consensus estimates, analyst targets, and four-quarter beat/miss history.
- `get_correlation_analysis`: 90-session return correlations and SPY Beta for two to five tickers.
- `get_superinvestor_holdings`: Public 13F smart-money holding changes from Dataroma/WhaleWisdom through 2MD.
- `get_insider_trading`: Public Form 4 insider activity from OpenInsider/Finviz/SEC pages through 2MD.
- `get_short_squeeze_analysis`: Short float, days-to-cover, and public borrow-fee evidence.
- `get_retail_sentiment`: Reddit WallStreetBets and StockTwits discussion signals through 2MD.
- `publish_to_wiki`: Publishes comprehensive financial reports, research documents, and multi-stock comparisons to David888 Wiki and returns a public shareUrl.

Users can converse with you freely in natural language to perform fundamental analysis, technical health checks, news summaries, transmission chain reasoning, multi-factor attribution, or market comparisons across Taiwan (e.g. 2330.TW) and US stocks (e.g. NVDA, TSLA).

Specialized macro commands available for users:
- **/ai2 <ticker>**: AI Hedge Fund 14 Legend Investor Committee & Round Table debate. If a user asks for multi-analyst debate or Warren Buffett / Cathie Wood committee opinions, guide them to try `/ai2 <ticker>`.
- **/chain <事件/主題>**: Financial logic transmission chain analysis (e.g. `/chain 聯準會降息` or `/chain 地緣政治升溫`) with Mermaid causal flowcharts.
- **/hot [cls|wallstreetcn|xueqiu]**: Real-time breaking financial news headlines from 財聯社, 華爾街見聞, or 雪球.
- **/chip <ticker>**: Taiwan stock institutional investors (TWSE/TPEX 三大法人) breakdown, foreign & trust streaks (連買/連賣天數), and 5-day accumulation (e.g. `/chip 2330.TW`, `/chip 3293`).
- **/ff <ticker>**: Fama-French multi-factor risk attribution & Alpha estimation (e.g. `/ff NVDA`).
- **/s <ticker>**: Generates Day/Week/Month K-line charts.
- **/p <ticker>**: Computes 5-day Prophet time-series forecast.
- **/sepa <ticker>**: Mark Minervini SEPA trend template and VCP screen.
- **/val <ticker>**: Five-year DCF valuation with WACC sensitivity.
- **/earn <ticker>**: Upcoming earnings and four-quarter surprise briefing.
- **/corr <ticker1,ticker2,...>**: Return correlation and SPY Beta for 2-5 stocks.

**David888 Wiki Publishing Guidelines (Mandatory):**
- When generating long-form reports or when the user asks to publish to Wiki or share as a link:
  1. ALWAYS ensure the document starts with `# Document Title` on the very first line. Never output conversational small talk or greetings before `# Title`.
  2. Put executive summary `> ...` and `[TOC]` right after the title.
  3. Use rich formatting: tables, GitHub alerts (`> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`), footnotes (`[^1]`), text highlights (`==text==`), and code tabs.
  4. Supported themes: `claude-canvas`, `retro`, `tokyo-night`, `notion-clean`, `botanical`, `professional`, `ayu-light`, `terminal`.
  5. ALWAYS provide the public `shareUrl` to the user.

**Your Role & Strict Guidelines:**
- **🛑 嚴禁爭辯與推拖 (Zero-Excuse & Zero-Arguing Policy)**:
  1. **絕對禁止與使用者爭辯**，嚴禁以「我是 AI 模型、我無法修改訓練權重」、「此代碼非公司本身」等說辭推拖。
  2. 當使用者指出事實錯誤時，立即以即時工具搜尋驗證最新市場事實。
  3. **已知上市公司實況**：SpaceX (Space Exploration Technologies Corp.) 已於 2026 年 6 月 12 日在美股那斯達克掛牌上市，股票代號為 **`SPCX`**（`NASDAQ:SPCX`）。當使用者詢問 SpaceX 股價、走勢或 DCF 估值時，直接以代碼 **`SPCX`** 調用對應行情與估值工具，**嚴禁斷言 SpaceX 是未上市私營公司**！
- **🔴 零幻覺與即時檢索鐵律 (ZERO HALLUCINATION & REAL-TIME SEARCH POLICY)**:
  1. 你的底層模型內部知識庫是過期的。面對任何關於**公司是否上市、IPO 狀態、股票代碼、股價、財務數據、即時新聞或近期事件**的問題，**嚴禁憑記憶回答，必須一律調用工具檢索**！
  2. 工具調用原則：
     - 若使用者詢問公司上市/IPO 狀態、查找股票代碼、近期動態或一般財經事件，請務必調用 **`search_financial_web`** 進行 2MD 即時連網搜尋。
     - 若已知明確股票代碼（如 SPCX, TSLA, NVDA, 2330.TW），請調用 **`get_financial_news`**、**`get_stock_prices`** 或 **`get_financial_metrics`**。
  3. **嚴禁任何自行腦補、猜測假新聞、假日期、假上市狀態或假數字**！
  4. 若工具搜尋結果為空或回傳錯誤，必須如實告知：「目前搜尋模組查無即時資訊/模組故障」，絕不准自行編造任何假資訊。
  5. 回覆時必須引述工具檢索到的實際內容與 Markdown 來源連結 (`[標題](URL)`)。
  6. 對 SEPA、DCF、earnings、correlation 或 smart-money 問題，優先使用對應專用工具；若資料缺失，清楚標示限制，絕不以猜測補值。
  7. 工具調用完成並獲取資料後，請立即綜合數據輸出完整的繁體中文分析結論，嚴禁重複發起工具調用或陷入死循環！
- **💼 專業投研語氣與嚴禁系統說教 (Zero-Preachiness & No Prompt Leakage)**:
  1. **絕對不要對用戶說教或輸出內部系統詞彙**（例如嚴禁向用戶說「這違反我的零幻覺原則」、「我的內部工具只能接受...」等生硬的機器人說詞）。
  2. 若用戶詢問尚未公開上市之私營公司（例如 Stripe, Anthropic 等）的估值或 DCF，請以專業投資銀行分析師的口吻回答：
     - 自然說明該公司尚未公開 IPO，無正式 SEC 財報可跑精確 DCF；
     - 主動調用 `search_financial_web` 搜尋最新一輪的**私募股權/次級市場 Tender Offer 估值**、預估營收/現金流與同業可比乘數（P/S 或 EV/Revenue），給出有實質價值的估值評估！
- **動態延伸續問設計 (Context-Aware Follow-up Prompts)**:
  在每次完整分析回答的最後，請根據本次對話的上下文深度、具體探討的標的或核心議題，量身設計 2 到 4 個最具針對性、非模板化、緊扣上下文的延伸續問建議（例如探討具體催化劑、風險盲點、供應鏈傳導或量化模型分析）。
  請將這 2~4 個建議以 JSON 陣列格式包裹在 `[FOLLOWUPS]` 標籤中置於回覆最末尾，範例：
  [FOLLOWUPS]
  [
    "📊 評估該標的在 2026 年的營收滲透率",
    "💰 計算其五年 DCF 內在價值 (/val 標的代碼)",
    "⚔️ 比較其與主要競爭對手的毛利率優勢"
  ]
  [/FOLLOWUPS]
- 始終以繁體中文 (Traditional Chinese) 禮貌、客觀、條理清晰且精準地回答。
    """)
    
    response = main_llm_with_tools.invoke([system_prompt] + messages)
    return {"messages": [response]}

def synthesizer_node(state: MainAgentState):
    messages = state["messages"]
    user_question = ""
    tool_outputs = []
    
    for msg in messages:
        if isinstance(msg, HumanMessage):
            user_question = msg.content
        elif isinstance(msg, ToolMessage):
            tool_outputs.append(f"【檢索/量化數據】:\n{msg.content}")

    context_text = "\n\n".join(tool_outputs) if tool_outputs else "無額外工具數據"
    synthesis_prompt = f"""你是一位頂級專業金融分析師與量化研究員。
請根據以下檢索到的即時市場與量化數據，為使用者的問題提供條理清晰、數據精確、專業詳盡的繁體中文分析回覆。

使用者問題："{user_question}"

即時檢索與量化數據：
{context_text}

回覆規範：
1. 請以繁體中文 (Traditional Chinese) 輸出結構清晰的分析報告。
2. 包含核心結論、財務/市場指標數據、估值情境與風險提示。
3. 嚴禁輸出 JSON 工具呼叫格式，直接輸出給使用者閱讀的 Markdown 文本。
4. 【動態延伸續問】：在分析結論的最末尾，根據剛剛討論的深度與情境，量身設計 2 到 4 個緊扣上下文、非模板化的延伸續問建議，包裹在 `[FOLLOWUPS]` 標籤中：
[FOLLOWUPS]
[
  "續問一 (10-25字)",
  "續問二",
  "續問三"
]
[/FOLLOWUPS]"""

    llm_without_tools = primary_llm.with_fallbacks([fallback_llm]) if FALLBACK_LLM_API_KEY else primary_llm
    response = llm_without_tools.invoke([HumanMessage(content=synthesis_prompt)])
    return {"messages": [AIMessage(content=response.content)]}

# Build Graph
agent_builder = StateGraph(MainAgentState)
agent_builder.add_node("agent", main_agent_node)
agent_builder.add_node("tools", ToolNode(main_agent_tools))
agent_builder.add_node("synthesizer", synthesizer_node)

agent_builder.add_edge(START, "agent")
agent_builder.add_conditional_edges(
    "agent",
    tools_condition,
    {"tools": "tools", END: END}
)
agent_builder.add_edge("tools", "synthesizer")
agent_builder.add_edge("synthesizer", END)

# Compile with memory persistence
main_agent_graph = agent_builder.compile(checkpointer=valid_memory)

# --- Fundamental Analyst Logic (/ai command) ---
fa_key = OPENAI_API_KEY or LLM_API_KEY or "dummy-key"
fa_model = OPENAI_MODEL if OPENAI_API_KEY else LLM_MODEL
fa_base_url = OPENAI_BASE_URL if OPENAI_API_KEY else LLM_BASE_URL

llm_fa_primary = ChatOpenAI(
    model=fa_model,
    api_key=fa_key,
    base_url=fa_base_url,
    temperature=0
)

if FALLBACK_LLM_API_KEY:
    llm_fa_fallback = ChatOpenAI(
        model=FALLBACK_LLM_MODEL,
        api_key=FALLBACK_LLM_API_KEY,
        base_url=FALLBACK_LLM_BASE_URL,
        temperature=0
    )
    llm_fa = llm_fa_primary.with_fallbacks([llm_fa_fallback])
else:
    llm_fa = llm_fa_primary

def fundamental_analyst(state: State):
    """Use tool chain for fundamental analysis (Legacy /ai command)"""
    stock = state['stock']
    user_question = state['messages'][0].content if state['messages'] else "Should I buy this stock?"
    
    try:
        # Manual invoke sequence
        price_data = get_stock_prices.invoke({"ticker": stock})
        metrics = get_financial_metrics.invoke({"ticker": stock})
        news = get_financial_news.invoke({"ticker": stock})
        
        analysis_prompt = f"""
        根據以下 {stock} 的資料，進行全面的基本面分析並回答使用者問題："{user_question}"
        
        股價與技術指標資料：
        {price_data}
        
        財務指標：
        {metrics}
        
        相關新聞：
        {news}
        
        請用繁體中文輸出。
        """
        
        response = llm_fa.invoke(analysis_prompt)
        return {"messages": [AIMessage(content=response.content)]}
        
    except Exception as e:
        return {"messages": [AIMessage(content=f"Error: {str(e)}")]}

import datetime as dt

# Session TTL tracking (3 days = 72 hours)
SESSION_TTL_SECONDS = 3 * 86400
session_last_active: Dict[str, dt.datetime] = {}

# Export functions
async def process_chat_message(user_input: str, thread_id: str = None) -> str:
    """Process a natural language message using the Main Agent with context memory and 3-day TTL."""
    try:
        expired_notice = ""
        now = dt.datetime.now()
        if thread_id:
            if thread_id in session_last_active:
                last_time = session_last_active[thread_id]
                if (now - last_time).total_seconds() > SESSION_TTL_SECONDS:
                    await clear_context(thread_id)
                    expired_notice = "💡 *(距離上次對話已超過 3 天，系統已自動為您重置記憶並開啟全新對話)*\n\n"
            session_last_active[thread_id] = now

        inputs = {"messages": [HumanMessage(content=user_input)]}
        
        # Configure thread-based persistence and recursion limit
        config = {
            "configurable": {"thread_id": thread_id} if thread_id else {},
            "recursion_limit": 12
        }
        
        result = await main_agent_graph.ainvoke(inputs, config=config)
        
        # Find the last AIMessage with non-empty content
        messages = result.get("messages", [])
        final_content = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                if isinstance(msg.content, str) and msg.content.strip():
                    final_content = msg.content.strip()
                    break
                elif isinstance(msg.content, list):
                    text_parts = [
                        b.get("text", "") if isinstance(b, dict) else str(b)
                        for b in msg.content
                    ]
                    joined = "\n".join(p for p in text_parts if p.strip()).strip()
                    if joined:
                        final_content = joined
                        break

        # Fallback if final AIMessage had no text (e.g. ended after tool execution)
        if not final_content:
            tool_outputs = []
            for msg in reversed(messages):
                if hasattr(msg, "content") and str(msg.content).strip():
                    tool_outputs.append(str(msg.content).strip())
                if len(tool_outputs) >= 2:
                    break
            if tool_outputs:
                final_content = f"已取得相關資訊：\n\n" + "\n\n".join(tool_outputs[:2])

        if final_content:
            return expired_notice + final_content
        return "抱歉，目前暫時無法取得該問題的完整分析結果，請稍後再試。"
    except Exception as e:
        logger.error(f"Main agent error: {e}")
        return f"❌ 處理訊息時發生錯誤：{str(e)}"

async def clear_context(thread_id: str):
    """Clear conversation history for a specific user (thread)."""
    if not thread_id:
        return
    
    count = 0
    keys_to_remove = []
    
    for key in list(valid_memory.storage.keys()):
        if isinstance(key, tuple) and key[0] == thread_id:
            keys_to_remove.append(key)
        elif key == thread_id:
            keys_to_remove.append(key)
            
    for k in keys_to_remove:
        try:
            del valid_memory.storage[k]
            count += 1
        except KeyError:
            pass
        
    session_last_active[thread_id] = dt.datetime.now()
    logger.info(f"Cleared {count} memory items for thread {thread_id}")


def extract_followups_from_text(text: str) -> tuple[str, list[str]]:
    """
    Extracts [FOLLOWUPS]...[/FOLLOWUPS] from LLM response.
    Returns (cleaned_markdown_text, followups_list).
    """
    if not text:
        return "", []
    m = re.search(r"\[FOLLOWUPS\](.*?)\[/FOLLOWUPS\]", text, re.DOTALL | re.IGNORECASE)
    if m:
        raw_json = m.group(1).strip()
        followups = []
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                followups = [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            lines = [l.strip("-* 1234567890.\"'\t") for l in raw_json.splitlines() if l.strip()]
            followups = [l for l in lines if l]
        cleaned_text = text[:m.start()].rstrip()
        return cleaned_text, followups
    return text, []
