"""Exercise all production handler registrations without starting polling."""

import asyncio
import unittest
from unittest.mock import patch

from telegram.ext import Application
import main


class BotStartupTests(unittest.TestCase):
    def test_all_handlers_register_before_polling(self):
        previous_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(previous_loop)
        try:
            with patch.object(main, "TELEGRAM_BOT_TOKEN", "123456:test-token"), patch.object(Application, "run_polling") as polling:
                main.main()
                polling.assert_called_once()
        finally:
            asyncio.get_event_loop().close()
            previous_loop.close()
            asyncio.set_event_loop(None)
