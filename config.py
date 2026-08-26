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

# --- AI Hedge Fund Microservice Endpoints ---
AI2_BASE_URL = os.getenv("AI2_BASE_URL", "http://dns.glsoft.ai:6000")
AI2_API_URL = os.getenv("AI2_API_URL", f"{AI2_BASE_URL}/api/analysis")
AI2_ROUND_TABLE_URL = os.getenv("AI2_ROUND_TABLE_URL", f"{AI2_BASE_URL}/api/round_table")
AI2_HEALTH_URL = os.getenv("AI2_HEALTH_URL", f"{AI2_BASE_URL}/api/health")

# --- 2MD Web Reader & SERP Search Endpoints (Primary & Backups) ---
TWOMD_PRIMARY_URL = os.getenv("TWOMD_PRIMARY_URL", "https://2md.aiurl.tw")
TWOMD_BACKUP1_URL = os.getenv("TWOMD_BACKUP1_URL", "https://2md.glsoft.ai")
TWOMD_BACKUP2_URL = os.getenv("TWOMD_BACKUP2_URL", "https://create360.ai")
TWOMD_SEARCH_ENDPOINTS = [
    TWOMD_PRIMARY_URL,
    TWOMD_BACKUP1_URL,
    TWOMD_BACKUP2_URL
]

# --- Main LLM Agent Configuration ---
# Protocol: OpenAI-compatible
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1") # Default to Groq if not set, or generic
LLM_MODEL = os.getenv("LLM_MODEL", "llama3-70b-8192") # Default model

# Telegram Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Font Management
FONT_URL = "https://drive.google.com/uc?id=1eGAsTN1HBpJAkeVM57_C7ccp7hbgSz3_"
TEMP_DIR = tempfile.mkdtemp()
