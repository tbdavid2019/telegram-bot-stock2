from telegram import Update, BotCommand, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, Application
import logging

logger = logging.getLogger(__name__)

from ai_core import clear_context
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Reset conversation context
    thread_id = str(update.effective_chat.id)
    await clear_context(thread_id)

    help_message = (
        "🎉 **歡迎使用 DAVID888 股票資訊與 AI 投資分析機器人！**\n\n"
        "*(您的對話記憶已重置，現在是一個全新的開始)*\n\n"
        "💬 **自然語言智能對話（直接傳送文字即可）**：\n"
        "機器人已整合量化模型、2MD 全網情報、即時股價、技術指標與新聞。您可以像與研究員對話一樣直接詢問：\n"
        "  • 📐 *「TSLA 目前符合 Minervini SEPA 突破與 Stage 2 嗎？」*\n"
        "  • 💰 *「幫我計算 AAPL 的五年 DCF 內在價值與合理價」*\n"
        "  • 🗓️ *「NVDA 下週財報預期與過去四季驚喜度如何？」*\n"
        "  • 🏛️ *「巴菲特和段永平最近有買進或加減持哪檔股票？(13F持倉)」*\n"
        "  • 🕵️ *「查詢 TSLA 最近的高階經理人內部人買賣 (Form 4)」*\n"
        "  • 🚀 *「分析 GME 的做空比率與軋空 (Short Squeeze) 風險」*\n"
        "  • 📰 *「台積電 2330.TW 最近有什麼重大新聞與基本面評估」*\n\n"
        "📌 **專屬量化與委員會指令速查**：\n"
        "• `/chain 事件或主題` - ⛓️ 金融邏輯傳導鏈分析與因果流程圖 (範例：`/chain 聯準會降息`)\n"
        "• `/hot [來源]` - 🔥 財聯社/華爾街見聞/雪球即時快訊 (範例：`/hot` 或 `/hot wallstreetcn`)\n"
        "• `/sepa 股票代碼` - 📐 Minervini SEPA 8 項趨勢模板與 VCP 篩選 (範例：`/sepa TSLA`)\n"
        "• `/val 股票代碼` - 💰 五年 DCF 內在價值與 WACC 敏感度 (範例：`/val AAPL`)\n"
        "• `/earn 股票代碼` - 🗓️ 財報日期、共識預估與四季驚喜紀錄 (範例：`/earn NVDA`)\n"
        "• `/corr 股票1,股票2,...` - 🔗 90 日相關係數與 S&P 500 Beta (範例：`/corr TSLA,NVDA,AAPL`)\n"
        "• `/ai2 股票代碼` - 🏛️ 14 位投資大師 AI 對沖基金委員會與圓桌辯論 (範例：`/ai2 NVDA`)\n"
        "• `/s 股票代碼` - 📈 查詢即時股價與 日/週/月 K 線圖 (範例：`/s 2330.TW`)\n"
        "• `/p 股票代碼` - 🔮 Prophet 時間序列預測未來 5 天股價區間 (範例：`/p META`)\n"
        "• `/n 股票代碼` - 📰 查詢美股即時英文新聞 (範例：`/n AAPL`)\n"
        "• `/ny 股票代碼` - 📰 查詢台股即時中文新聞 (範例：`/ny 2330.TW`)\n"
        "• `/h` - 🛠️ 顯示其他外部量化預測工具連結\n"
        "• `/start` 或 `/help` - 🔄 重置記憶並顯示此說明選單"
    )
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("/chain 聯準會降息 傳導鏈分析"), KeyboardButton("/hot 即時重大快訊")],
            [KeyboardButton("/sepa TSLA SEPA趨勢分析"), KeyboardButton("/val AAPL DCF估值計算")],
            [KeyboardButton("/earn NVDA 財報前瞻簡報"), KeyboardButton("/corr TSLA,NVDA,AAPL 相關性分析")],
            [KeyboardButton("/ai2 NVDA 14大師圓桌辯論"), KeyboardButton("/s 2330.TW 查詢K線圖")],
            [KeyboardButton("分析 2330.TW 基本面與技術面"), KeyboardButton("/p META Prophet預測")]
        ],
        resize_keyboard=True
    )
    await update.message.reply_text(help_message, reply_markup=keyboard, parse_mode="Markdown")

async def tools_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "🛠 **其他股票與量化工具**\n\n"
        "📊 台股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-predict)\n"
        "📈 美股台股潛力股預測 (LSTM)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/twStock-Underdogs)\n"
        "🔮 美股台股預測 (Prophet)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/Stock-Predict-Prophet)\n"
        "🏛️ AI 對沖基金 (14位投資大師與圓桌辯論)：[點擊使用](https://huggingface.co/spaces/tbdavid2019/ai-hedge-fund)"
    )
    await update.message.reply_text(message, parse_mode="Markdown")


from ai_core import process_chat_message

async def default_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle regular text messages by passing them to the Main LLM Agent.
    This enables natural language interaction (e.g., 'How is TSLA doing?').
    """
    user_input = update.message.text
    if not user_input:
        return

    # Notify user that bot is typing and send temporary status message
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text("⏳ 思考與處理中，請稍候...")
    
    try:
        # Process message via Main Agent with conversation memory
        thread_id = str(update.effective_chat.id)
        response = await process_chat_message(user_input, thread_id=thread_id)
        
        # Delete the temporary processing message
        try:
            await processing_msg.delete()
        except Exception:
            pass

        try:
            await update.message.reply_text(response, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Default message handler error: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"❌ 處理訊息時發生錯誤：{str(e)}")


async def reset_commands(application: Application):
    commands = [
        BotCommand("start", "啟動機器人與重置對話記憶"),
        BotCommand("chain", "金融邏輯傳導鏈分析 (因果流程圖)"),
        BotCommand("hot", "即時重大財經快訊 (財聯社/華爾街見聞)"),
        BotCommand("ai2", "14位投資大師圓桌辯論 (AI對沖基金)"),
        BotCommand("s", "查詢即時股價和日/週/月 K 線圖"),
        BotCommand("p", "Prophet 模型預測未來 5 天股價"),
        BotCommand("sepa", "Minervini SEPA 趨勢模板與 VCP 分析"),
        BotCommand("val", "五年 DCF 內在價值與 WACC 敏感度"),
        BotCommand("earn", "財報日期與四季盈餘驚喜簡報"),
        BotCommand("corr", "多股相關係數與 S&P 500 Beta"),
        BotCommand("n", "查詢美股即時新聞"),
        BotCommand("ny", "查詢台股即時新聞"),
        BotCommand("h", "顯示量化預測工具連結"),
        BotCommand("help", "顯示完整功能說明與指令表")
    ]
    await application.bot.set_my_commands(commands)
