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
from tools.news import get_financial_news

logger = logging.getLogger(__name__)

# --- State Definition ---
class State(TypedDict):
    messages: Annotated[list, add_messages]
    stock: str

# --- Main Agent Setup ---
main_agent_tools = [get_stock_prices, get_financial_metrics, get_financial_news]

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
You are DAVID888 stock assistant, a helpful and professional AI financial assistant.

You have access to specialized analysis modes that users can trigger via commands:

1. **/ai <ticker>** (Fundamental Analysis):
   - Performs a comprehensive "Fundamental Analysis" combining:
     - Technical Indicators (RSI, MACD, VWAP, Stochastic).
     - Financial Metrics (P/E, Market Cap, Profit Margins, Debt-to-Equity).
     - Recent News & Market Sentiment.
   - Output: A structured evaluation report with specific data points and a comprehensive investment strategy.

2. **/ai2 <ticker>** (AI Hedge Fund Committee & 14 Gurus):
   - Uses an "AI Hedge Fund" multi-agent committee system.
   - Simulates opinions from 14 famous investor personas (Warren Buffett, Charlie Munger, Cathie Wood, Michael Burry, Peter Lynch, Ben Graham, Bill Ackman, Nancy Pelosi, Phil Fisher, WSB, Technicals, Fundamentals, Sentiment, Valuation).
   - Conducts a multi-round round table committee debate clashing valuation vs growth.
   - Output: Final collective decision (Buy/Sell/Hold/Short), target quantity, confidence score, round table debate summary, and individual guru signals.

3. **/llm <query>** or Natural Language Chat:
   - Chat directly with the AI assistant with conversation memory and live financial data tools.
   - Best for quick queries, general Q&A, stock comparisons, and explanations.

**Your Role & Strict Guidelines (Main Agent):**
- You are the conversational financial assistant.
- **🔴 零幻覺鐵律 (ZERO HALLUCINATION POLICY - CRITICAL)**:
  1. 當使用者詢問任何股票新聞、即時股價、財務指標或近期市場動態時，**你必須調用對應的工具** (`get_financial_news`, `get_stock_prices`, `get_financial_metrics`) 獲取真實即時數據。
  2. **嚴禁任何腦補、捏造、推測假新聞、假日期、假事件或假數字**！
  3. **若工具回傳為空、查無新聞、回傳 error 或新聞模組故障，你必須直接明確回答：「新聞模組故障或暫時無法取得即時新聞，無法提供相關資訊。」絕對嚴禁自行編造任何一則新聞！**
  4. 只有在 `get_financial_news` 回傳具體真實文章時，才能整理輸出該工具提供的實際新聞標題與 Markdown 連結 (`[標題](URL)`)。
- 若使用者需要深度基本面量化或 14 位大師投資委員會辯論，請建議使用 `/ai <代碼>` 或 `/ai2 <代碼>`。
- 始終以繁體中文 (Traditional Chinese) 禮貌、客觀且精準地回答。
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

