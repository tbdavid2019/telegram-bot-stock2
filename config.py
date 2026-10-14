import os
import logging
import tempfile
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Logging Configuration ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration Constants ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", None)

# --- AI Hedge Fund API v2 Microservice Endpoints ---
AI2_BASE_URL = os.getenv("AI2_BASE_URL", "https://hedgeapi.afpicapital.com")
AI2_API_URL = os.getenv("AI2_API_URL", f"{AI2_BASE_URL}/api/analysis")
AI2_ROUND_TABLE_URL = os.getenv("AI2_ROUND_TABLE_URL", f"{AI2_BASE_URL}/api/round_table")
AI2_HEALTH_URL = os.getenv("AI2_HEALTH_URL", f"{AI2_BASE_URL}/api/health")
AI2_BACKTEST_GRID_URL = os.getenv("AI2_BACKTEST_GRID_URL", f"{AI2_BASE_URL}/api/backtest/grid")
AI2_BACKTEST_RUN_URL = os.getenv("AI2_BACKTEST_RUN_URL", f"{AI2_BASE_URL}/api/backtest/runs")
AI2_MODEL_NAME = os.getenv("AI2_MODEL_NAME", "openai/gpt-oss-20b")
AI2_MODEL_PROVIDER = os.getenv("AI2_MODEL_PROVIDER", "Groq")
AI2_TIMEOUT = float(os.getenv("AI2_TIMEOUT", "180"))

# --- 2MD Web Reader & SERP Search Endpoints (Primary & Backups) ---
TWOMD_PRIMARY_URL = os.getenv("TWOMD_PRIMARY_URL", "https://2md.aiurl.tw")
TWOMD_BACKUP1_URL = os.getenv("TWOMD_BACKUP1_URL", "https://2md.glsoft.ai")
TWOMD_BACKUP2_URL = os.getenv("TWOMD_BACKUP2_URL", "https://create360.ai")
TWOMD_SEARCH_ENDPOINTS = [
    TWOMD_PRIMARY_URL,
    TWOMD_BACKUP1_URL,
    TWOMD_BACKUP2_URL
]

# --- David888 Wiki Publisher Endpoints ---
WIKI_BASE_URL = os.getenv("WIKI_BASE_URL", "https://wiki.david888.com")
WIKI_API_URL = os.getenv("WIKI_API_URL", f"{WIKI_BASE_URL}/api")

# --- 888 Stock Quant Platform Endpoints ---
STOCKDATA_BASE_URL = os.getenv("STOCKDATA_BASE_URL", "https://stockdata.david888.com")

# --- Main LLM Agent Configuration (Primary: NEN deepseek-v4-flash, Fallback: Groq) ---
# Protocol: OpenAI-compatible
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-XqYJN7YDjomSEeOPn9GsHvSpspYLuQrxdgQc2zcA3kvuZD34")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://nen.com.tw/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

# Fallback LLM (Groq)
FALLBACK_LLM_API_KEY = os.getenv("FALLBACK_LLM_API_KEY", os.getenv("GROQ_API_KEY"))
FALLBACK_LLM_BASE_URL = os.getenv("FALLBACK_LLM_BASE_URL", "https://api.groq.com/openai/v1")
FALLBACK_LLM_MODEL = os.getenv("FALLBACK_LLM_MODEL", "openai/gpt-oss-20b")

# Telegram Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Font Management
FONT_URL = "https://drive.google.com/uc?id=1eGAsTN1HBpJAkeVM57_C7ccp7hbgSz3_"
TEMP_DIR = tempfile.mkdtemp()
