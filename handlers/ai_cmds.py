import json
import logging
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from langchain_core.messages import HumanMessage
from config import AI2_API_URL
from ai_core import process_chat_message

logger = logging.getLogger(__name__)

# 14 Analyst Personas Mapping (key -> emoji, display name)
ANALYST_PERSONAS = {
    "warren_buffett": ("👴", "華倫·巴菲特 (Warren Buffett)"),
    "charlie_munger": ("🧓", "查理·蒙格 (Charlie Munger)"),
    "ben_graham": ("📚", "班傑明·葛拉漢 (Ben Graham)"),
    "cathie_wood": ("👩‍💼", "凱西·伍德 (Cathie Wood)"),
    "bill_ackman": ("🦈", "比爾·艾克曼 (Bill Ackman)"),
    "nancy_pelosi": ("🏛️", "南西·裴洛西 (Nancy Pelosi)"),
    "michael_burry": ("👁️", "邁克爾·貝瑞 (Michael Burry)"),
    "peter_lynch": ("🛍️", "彼得·林區 (Peter Lynch)"),
    "phil_fisher": ("🔍", "菲利普·費雪 (Phil Fisher)"),
    "wsb": ("🦍", "華爾街賭場 (WallStreetBets)"),
    "technical_analyst": ("📉", "技術分析師 (Technicals)"),
    "fundamentals_analyst": ("📈", "基本面分析師 (Fundamentals)"),
    "sentiment_analyst": ("🌐", "市場情緒分析師 (Sentiment)"),
    "valuation_analyst": ("⚖️", "估值分析師 (Valuation)")
}

ALL_ANALYST_KEYS = list(ANALYST_PERSONAS.keys())

async def safe_reply_markdown(update: Update, text: str):
    """Safely reply with Markdown, falling back to plain text if parse error occurs."""
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Markdown send failed ({e}), falling back to plain text")
        await update.message.reply_text(text)

async def ai_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified /ai command: Forward to Main Conversational Agent with tools & memory."""
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ai TSLA 或 /ai 2330.TW\n💡 提示：您也可以直接傳送文字「分析 TSLA 基本面」與機器人對話！")
        return

    ticker = context.args[0].upper()
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text(f"📊 正在為您全面診斷 {ticker}（整合即時行情、財務指標、技術分析與新聞），請稍候...")
    
    prompt = f"請針對 {ticker} 進行全面的基本面財務指標、技術面指標（如 RSI/MACD/VWAP）與近期即時新聞綜合評估診斷，並給出清晰的投資策略分析。"
    
    try:
        thread_id = str(update.effective_chat.id)
        response = await process_chat_message(prompt, thread_id=thread_id)

        # Delete processing status message
        try:
            await processing_msg.delete()
        except Exception:
            pass

        await safe_reply_markdown(update, response)

    except Exception as e:
        logger.error(f"AI Analysis Forward Error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 分析時發生錯誤：{str(e)}")

async def ai2_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI Hedge Fund Committee Analysis (/ai2) across 14 Legend Investor Personas."""
    if len(context.args) == 0:
        await update.message.reply_text("❌ 請提供股票代碼，例如：/ai2 TSLA 或 /ai2 NVDA 或 /ai2 2330.TW")
        return
    
    ticker = context.args[0].upper()
    processing_msg = await update.message.reply_text(f"🏛️ 正在召開 14 位投資大師委員會與圓桌辯論分析 {ticker}，這需要約 15~30 秒，請稍候...")

    headers = {"Content-Type": "application/json"}
    payload = {
        "tickers": ticker,
        "selectedAnalysts": ALL_ANALYST_KEYS,
        "enableRoundTable": True,
        "roundTableRounds": 2,
        "initialCash": 100000
    }
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(AI2_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
        decisions_dict = data.get("decisions", {})
        ticker_data = data.get("analyst_signals", {})
        round_table_dict = data.get("round_table", {})
        
        # Match ticker key across case variants
        decision = (
            decisions_dict.get(ticker) or 
            decisions_dict.get(ticker.upper()) or 
            decisions_dict.get(ticker.lower()) or 
            (next(iter(decisions_dict.values()), None) if decisions_dict else None)
        )
        
        round_table_info = (
            round_table_dict.get(ticker) or 
            round_table_dict.get(ticker.upper()) or 
            round_table_dict.get(ticker.lower()) or 
            (next(iter(round_table_dict.values()), None) if round_table_dict else None)
        )
        
        # Delete processing message once data is retrieved
        try:
            await processing_msg.delete()
        except Exception:
            pass

        if not decision:
            await update.message.reply_text(f"⚠️ 未能獲取 {ticker} 的決策數據，請確認代碼是否正確。")
            return

        # Action formatting
        action_map = {
            "buy": "🟢 買入 (BUY)",
            "sell": "🔴 賣出 (SELL)",
            "hold": "⚪ 持有 (HOLD)",
            "short": "🔻 做空 (SHORT)"
        }
        raw_action = str(decision.get("action", "hold")).lower()
        action_text = action_map.get(raw_action, raw_action.upper())
        confidence = decision.get("confidence", 0)
        quantity = decision.get("quantity", 0)
        reasoning = decision.get("reasoning", "無詳細說明")

        # --- Part 1: Final Decision & Round Table Debate ---
        msg1 = f"🏛️ **{ticker} AI 對沖基金委員會決策報告**\n\n"
        msg1 += f"🎯 **最終決策**：{action_text}\n"
        msg1 += f"📊 **信心度**：`{confidence}%`\n"
        msg1 += f"📦 **建議配置數量**：`{quantity}` 股\n\n"
        msg1 += f"💡 **執行理由**：\n{reasoning}\n\n"

        if round_table_info and isinstance(round_table_info, dict):
            consensus = round_table_info.get("consensus_view")
            summary = round_table_info.get("discussion_summary")
            dissenting = round_table_info.get("dissenting_opinions")
            
            msg1 += "━━━━━━━━━━━━━━━━━━━━\n"
            msg1 += "🗣️ **圓桌委員會辯論精要 (Round Table)**\n\n"
            if consensus:
                msg1 += f"🤝 **委員會共識 (Consensus)**：\n{consensus}\n\n"
            if dissenting:
                msg1 += f"⚡ **分歧觀點 (Dissenting)**：\n{dissenting}\n\n"
            if summary and not consensus:
                msg1 += f"📝 **辯論總結**：\n{summary}\n\n"

        await safe_reply_markdown(update, msg1)

        # --- Part 2: 14 Legend Analysts Breakdown ---
        signal_map = {
            "bullish": "🟢 看多 (Bullish)",
            "bearish": "🔴 看空 (Bearish)",
            "neutral": "⚪ 中立 (Neutral)"
        }

        msg2 = f"👥 **{ticker} 14 位投資大師與專家觀點速覽**\n━━━━━━━━━━━━━━━━━━━━\n"
        
        # Build normalized lookup for analyst signals
        norm_signals = {}
        for k, v in ticker_data.items():
            clean_k = k.replace("_agent", "")
            norm_signals[clean_k] = v
            norm_signals[k] = v

        analyst_count = 0
        for analyst_key, (emoji, display_name) in ANALYST_PERSONAS.items():
            agent_payload = norm_signals.get(analyst_key) or norm_signals.get(f"{analyst_key}_agent")
            
            if not agent_payload or not isinstance(agent_payload, dict):
                continue
                
            info = (
                agent_payload.get(ticker) or 
                agent_payload.get(ticker.upper()) or 
                agent_payload.get(ticker.lower()) or 
                (next(iter(agent_payload.values()), None) if agent_payload else None)
            )
            
            if not info or not isinstance(info, dict):
                continue
                
            sig_raw = str(info.get("signal", "neutral")).lower()
            sig_text = signal_map.get(sig_raw, sig_raw)
            sig_conf = info.get("confidence", "N/A")
            sig_reason = info.get("reasoning", "")
            
            # Shorten reason for telegram if very long
            if len(sig_reason) > 200:
                sig_reason = sig_reason[:200] + "..."

            msg2 += f"\n{emoji} **{display_name}**\n"
            msg2 += f"   • 信號：{sig_text} | 信心：`{sig_conf}%`\n"
            if sig_reason:
                msg2 += f"   • 觀點：{sig_reason}\n"
            analyst_count += 1

        if analyst_count > 0:
            # Check length before sending
            if len(msg2) > 4000:
                # Split in half
                half_len = len(msg2) // 2
                split_idx = msg2.rfind("\n\n", 0, half_len)
                if split_idx == -1: split_idx = half_len
                await safe_reply_markdown(update, msg2[:split_idx])
                await safe_reply_markdown(update, msg2[split_idx:])
            else:
                await safe_reply_markdown(update, msg2)

    except httpx.HTTPStatusError as e:
        logger.error(f"AI2 HTTP Error: {e.response.status_code} - {e.response.text}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 呼叫 AI Hedge Fund API 失敗 (HTTP {e.response.status_code})")
    except Exception as e:
        logger.error(f"AI2 Error: {e}", exc_info=True)
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 分析失敗: {str(e)}")

async def llm_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Natural Language Assistant Query (/llm command) with conversation memory and live tools."""
    query = " ".join(context.args) if context.args else None
    if not query:
        await update.message.reply_text("❌ 請提供問題，例如：/llm 2330.TW 的近期營收與技術面如何？")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text("⏳ 思考與處理中，請稍候...")
    
    try:
        thread_id = str(update.effective_chat.id)
        response = await process_chat_message(query, thread_id=thread_id)
        
        # Delete temporary processing message
        try:
            await processing_msg.delete()
        except Exception:
            pass

        await safe_reply_markdown(update, response)
    except Exception as e:
        logger.error(f"LLM Query Error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 回應失敗: {str(e)}")
