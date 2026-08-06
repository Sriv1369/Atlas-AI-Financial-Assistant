import os
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv

# Load configurations
from config import TELEGRAM_BOT_TOKEN, GEMINI_API_KEY
import database
from bot_handlers import start_handler, text_handler, voice_handler, document_handler, photo_handler
from tools.google_tools import start_oauth_callback_server
import scheduler

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    """
    Run initialization tasks after the bot is started.
    """
    # 1. Initialize SQLite Database
    database.init_db()
    
    # 2. Start local OAuth callback server for Google integrations
    try:
        start_oauth_callback_server()
    except Exception as e:
        logger.error(f"Failed to start OAuth server: {e}")
        
    # 3. Initialize and start the background scheduler
    try:
        scheduler.init_scheduler(application.bot)
    except Exception as e:
        logger.error(f"Failed to start background scheduler: {e}")
        
    logger.info("Bot post-initialization completed successfully.")

def main() -> None:
    """
    Start the Telegram Bot.
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN is missing! Please configure it in your .env file.")
        return
        
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is missing! Bot will not be able to answer natural language queries.")
        
    # Build Telegram Bot application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start_handler))
    
    # Register message handlers
    # Process text messages
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    # Process voice notes
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))
    
    # Process uploaded documents (PDFs, spreadsheets, text files)
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    
    # Process uploaded photos
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    
    logger.info("Starting Atlas Financial Assistant bot polling...")
    # Run the bot in polling mode (keeps running until interrupted)
    application.run_polling()

if __name__ == '__main__':
    main()
