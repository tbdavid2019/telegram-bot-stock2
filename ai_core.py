import os
import logging
from typing import TypedDict, Annotated, List, Dict
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
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
from tools.news import get_financial_news, search_financial_web
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
    temperature=0.5,
    max_tokens=2048
)
primary_with_tools = primary_llm.bind_tools(main_agent_tools)

# Initialize Fallback LLM (Groq) if configured
if FALLBACK_LLM_API_KEY:
    fallback_llm = ChatOpenAI(
        model=FALLBACK_LLM_MODEL,
        api_key=FALLBACK_LLM_API_KEY,
        base_url=FALLBACK_LLM_BASE_URL,
        temperature=0.5,
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

Users can converse with you freely in natural language to perform fundamental analysis, technical health checks, news summaries, or market comparisons across Taiwan (e.g. 2330.TW) and US stocks (e.g. NVDA, TSLA).

Specialized macro commands available for users:
- **/ai2 <ticker>**: AI Hedge Fund 14 Legend Investor Committee & Round Table debate. If a user asks for multi-analyst debate or Warren Buffett / Cathie Wood committee opinions, guide them to try `/ai2 <ticker>`.
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
- **🔴 零幻覺與即時檢索鐵律 (ZERO HALLUCINATION & REAL-TIME SEARCH POLICY)**:
  1. 你的底層模型內部知識庫是過期的。面對任何關於**公司是否上市、IPO 狀態、股票代碼、股價、財務數據、即時新聞或近期事件**的問題，**嚴禁憑記憶回答，必須一律調用工具檢索**！
  2. 工具調用原則：
     - 若使用者詢問公司上市/IPO 狀態、查找股票代碼、近期動態或一般財經事件（例如：「SpaceX 上市了嗎」、「台積電最新消息」），請務必調用 **`search_financial_web`** 進行 2MD 即時連網搜尋。
     - 若已知明確股票代碼（如 TSLA, 2330.TW），請調用 **`get_financial_news`**、**`get_stock_prices`** 或 **`get_financial_metrics`**。
  3. **嚴禁任何自行腦補、猜測假新聞、假日期、假上市狀態或假數字**！
  4. 若工具搜尋結果為空或回傳錯誤，必須如實告知：「目前搜尋模組查無即時資訊/模組故障」，絕不准自行編造任何假資訊。
  5. 回覆時必須引述工具檢索到的實際內容與 Markdown 來源連結 (`[標題](URL)`)。
  6. 對 SEPA、DCF、earnings、correlation 或 smart-money 問題，優先使用對應專用工具；若資料缺失，清楚標示限制，絕不以猜測補值。
- 始終以繁體中文 (Traditional Chinese) 禮貌、客觀、條理清晰且精準地回答。
    """)
    
    response = main_llm_with_tools.invoke([system_prompt] + messages)
    return {"messages": [response]}

# Build Graph
agent_builder = StateGraph(MainAgentState)
agent_builder.add_node("agent", main_agent_node)
agent_builder.add_node("tools", ToolNode(main_agent_tools))

agent_builder.add_edge(START, "agent")
agent_builder.add_conditional_edges("agent", tools_condition)
agent_builder.add_edge("tools", "agent")

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

# Export functions
async def process_chat_message(user_input: str, thread_id: str = None) -> str:
    """Process a natural language message using the Main Agent with context memory."""
    try:
        inputs = {"messages": [HumanMessage(content=user_input)]}
        
        # Configure thread-based persistence
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        
        result = await main_agent_graph.ainvoke(inputs, config=config)
        
        # Get last message
        last_msg = result["messages"][-1]
        return last_msg.content
    except Exception as e:
        logger.error(f"Main agent error: {e}")
        return f"Sorry, I encountered an error: {str(e)}"

async def clear_context(thread_id: str):
    """Clear conversation history for a specific user (thread)."""
    if not thread_id:
        return
    
    # MemorySaver stores data in self.storage dictionary.
    # We iterate and remove keys belonging to this thread_id.
    # Note: This accesses internal storage of MemorySaver.
    count = 0
    keys_to_remove = []
    
    # valid_memory.storage keys are typically tuples involving thread_id
    # e.g. (thread_id, checkpoint_id)
    for key in valid_memory.storage.keys():
        if isinstance(key, tuple) and key[0] == thread_id:
            keys_to_remove.append(key)
        # Fallback if keys are structured differently in future versions
        elif key == thread_id:
            keys_to_remove.append(key)
            
    for k in keys_to_remove:
        del valid_memory.storage[k]
        count += 1
        
    logger.info(f"Cleared {count} memory items for thread {thread_id}")
