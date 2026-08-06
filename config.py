import os
import logging
from dotenv import load_dotenv

# Set up logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load .env file
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_PORT = int(os.getenv("PORT", os.getenv("GOOGLE_REDIRECT_PORT", "8080")))

DATABASE_PATH = os.getenv("DATABASE_PATH", "assistant.db")
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")

# Validation
if not TELEGRAM_BOT_TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN is not set. The Telegram bot will not start.")
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set. AI capabilities will be disabled.")
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    logger.warning("GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set. Google integrations will be disabled.")
