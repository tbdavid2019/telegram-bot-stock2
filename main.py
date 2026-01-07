#!/usr/bin/env python
import logging
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from config import TELEGRAM_BOT_TOKEN
from handlers.general import start, tools_help, default_message_handler, reset_commands
from handlers.stock_cmds import stock_info, stock_news, taiwan_stock_news, prophet_predict
from handlers.ai_cmds import ai_query, ai2_analysis, llm_query

# Configure Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log") # Log to file as well
    ]
)
logger = logging.getLogger(__name__)

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is not set in environment!")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("s", stock_info))
    app.add_handler(CommandHandler("n", stock_news))
    app.add_handler(CommandHandler("ny", taiwan_stock_news))
    app.add_handler(CommandHandler("p", prophet_predict))
    app.add_handler(CommandHandler("ai", ai_query))
    app.add_handler(CommandHandler("ai2", ai2_analysis))
    app.add_handler(CommandHandler("llm", llm_query))
    app.add_handler(CommandHandler("h", tools_help))
    
    # Default handler for non-commands
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, default_message_handler))

    # Reset commands on startup
    loop = asyncio.get_event_loop()
    loop.run_until_complete(reset_commands(app))

    logger.info("🚀 Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()