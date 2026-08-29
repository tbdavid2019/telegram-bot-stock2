#!/usr/bin/env python
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from config import TELEGRAM_BOT_TOKEN
from handlers.general import start, tools_help, default_message_handler, reset_commands
from handlers.stock_cmds import (
    stock_info,
    stock_news,
    taiwan_stock_news,
    prophet_predict,
    sepa_analysis,
    valuation_analysis,
    earnings_briefing,
    correlation_analysis,
)
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

    # Configure ThreadPoolExecutor for background sync I/O tasks (yfinance, Prophet, scraping)
    executor = ThreadPoolExecutor(max_workers=32)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_default_executor(executor)

    # Build Application with non-blocking concurrent updates and post_init hook
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(reset_commands)
        .build()
    )
    
    # Register Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("s", stock_info))
    app.add_handler(CommandHandler("n", stock_news))
    app.add_handler(CommandHandler("ny", taiwan_stock_news))
    app.add_handler(CommandHandler("p", prophet_predict))
    app.add_handler(CommandHandler("sepa", sepa_analysis))
    app.add_handler(CommandHandler("val", valuation_analysis))
    app.add_handler(CommandHandler("earn", earnings_briefing))
    app.add_handler(CommandHandler("corr", correlation_analysis))
    app.add_handler(CommandHandler("ai", ai_query))
    app.add_handler(CommandHandler("ai2", ai2_analysis))
    app.add_handler(CommandHandler("llm", llm_query))
    app.add_handler(CommandHandler("h", tools_help))
    
    # Default handler for non-commands
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, default_message_handler))

    logger.info("🚀 Bot started successfully with concurrent_updates=True (non-blocking mode)...")
    app.run_polling()

if __name__ == "__main__":
    main()
