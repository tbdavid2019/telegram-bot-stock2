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
DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "http://llm.glsoft.ai/v1/chat-messages")
DIFY_API_KEY = os.getenv("DIFY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# API URL for AI2 Analysis
AI2_API_URL = "http://dns.glsoft.ai:6000/api/analysis"

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
