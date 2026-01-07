import json
import logging
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from langchain_core.messages import HumanMessage
from config import DIFY_API_KEY, DIFY_BASE_URL, AI2_API_URL
from ai_core import fundamental_analyst

logger = logging.getLogger(__name__)

async def ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ai TSLA")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"🤖 正在分析 {ticker}，請稍候...")
    
    try:
        state = {
            "stock": ticker, 
            "messages": [HumanMessage(content="Should I buy this stock?")]
        }
        
        # Async invoke if possible? fundamental_analyst is sync in current def.
        # Run in thread
        import asyncio
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, fundamental_analyst, state)

        final_answer = "(No response)"
        if result.get("messages"):
            final_answer = result["messages"][-1].content

        await update.message.reply_text(f"🤖 **基本面分析回應**：\n\n{final_answer}", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"AI Analysis Error: {e}")
        await update.message.reply_text(f"❌ 分析時發生錯誤：{str(e)}")

async def ai2_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ai2 TSLA")
        return
    
    ticker = context.args[0].upper()
    await update.message.reply_text(f"🔍 正在分析 {ticker}，這可能需要幾秒鐘...")

    headers = {"Content-Type": "application/json"}
    payload = {
        "tickers": ticker.lower(),
        "selectedAnalysts": [
            "ben_graham", "bill_ackman", "cathie_wood", "charlie_munger", "michael_burry", 
            "peter_lynch", "phil_fisher", "nancy_pelosi", "warren_buffett", "wsb", 
            "technical_analyst", "fundamentals_analyst", "sentiment_analyst", "valuation_analyst"
        ],
        "modelName": "gpt-4o"
    }
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(AI2_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
        ticker_data = data["analyst_signals"]
        decisions = data["decisions"].get(ticker.lower())
        
        if not decisions:
             await update.message.reply_text("❌ 無法獲取決策數據")
             return

        # Translate Action
        action_map = {"buy": "買入", "sell": "賣出", "hold": "持有", "short": "做空"}
        action = action_map.get(decisions['action'].lower(), decisions['action'].upper())
        
        reply = f"📊 **{ticker} 多位投資大師分析結果**\n\n"
        reply += f"**最終決策**: {action} (信心度: {decisions['confidence']}%)\n"
        reply += f"**建議數量**: {decisions['quantity']} 股\n"
        reply += f"**理由**: {decisions['reasoning']}\n\n"
        reply += "**各投資大師觀點**:\n"
        
        key_analysts = {
            "warren_buffett_agent": "👴 華倫·巴菲特",
            "cathie_wood_agent": "👩‍💼 凱西·伍德",
            "charlie_munger_agent": "🧓 查理·蒙格",
            "wsb_agent": "🦍 華爾街賭場",
            "fundamentals_agent": "📈 基本面分析師",
            "technical_analyst_agent": "📉 技術分析師",
        }
        
        signal_map = {"bearish": "🔴 看空", "bullish": "🟢 看多", "neutral": "⚪ 中立"}
        
        for agent_name, agent_data in ticker_data.items():
            if agent_name in key_analysts and ticker.lower() in agent_data:
                info = agent_data[ticker.lower()]
                signal = signal_map.get(info.get("signal", "neutral"), info.get("signal"))
                conf = info.get("confidence", "N/A")
                reply += f"{key_analysts[agent_name]}: {signal} (信心度: {conf}%)\n"
                
        await update.message.reply_text(reply, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"AI2 Error: {e}")
        await update.message.reply_text(f"❌ 分析失敗: {str(e)}")

async def llm_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else None
    if not query:
        await update.message.reply_text("❌ 請提供問題，例如：/llm AVGO 的股價前景？")
        return

    headers = {
        "Authorization": f"Bearer {DIFY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": "",
        "user": str(update.effective_user.id)
    }

    await update.message.reply_text("🤖 正在生成回應...")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", DIFY_BASE_URL, json=payload, headers=headers) as response:
                response.raise_for_status()
                
                ai_response = ""
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        try:
                            chunk = json.loads(line[5:].strip())
                            if "answer" in chunk:
                                ai_response += chunk["answer"]
                        except:
                            pass
                            
                if ai_response:
                    await update.message.reply_text(f"🤖 **AI 回應**：\n\n{ai_response}", parse_mode="Markdown")
                else:
                    await update.message.reply_text("⚠️ 無法獲取回應")

    except Exception as e:
        logger.error(f"LLM Query Error: {e}")
        await update.message.reply_text(f"❌ 錯誤: {str(e)}")
