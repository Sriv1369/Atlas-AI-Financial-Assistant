import os
import logging
from telegram import Update
from telegram.ext import ContextTypes
import google.generativeai as genai

from agent import FinancialAgent
from tools.document_tools import process_uploaded_document
import database
from config import GEMINI_MODEL

logger = logging.getLogger(__name__)

# Directory for storing downloaded media files
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /start command. Prepares the user and initiates onboarding conversation.
    """
    chat_id = update.effective_chat.id
    user_name = update.effective_user.first_name
    
    # Initialize user in DB
    user = database.get_user(chat_id)
    if not user:
        database.create_or_update_user(chat_id, name=user_name, onboarding_status='not_started', onboarding_step=1)
    else:
        # Reset onboarding status to restart if they type start again
        database.create_or_update_user(chat_id, name=user_name, onboarding_status='not_started', onboarding_step=1)
        
    logger.info(f"User {chat_id} started the bot. Initiating onboarding.")
    
    # Pass to the agent to generate a welcoming onboarding message
    agent = FinancialAgent(chat_id)
    welcome_text = agent.chat("Start onboarding and greet me.")
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming natural language text messages.
    """
    chat_id = update.effective_chat.id
    user_msg = update.message.text
    
    # Send "typing" action to Telegram to feel responsive
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    agent = FinancialAgent(chat_id)
    response_text = agent.chat(user_msg)
    
    # Send response back to the user
    await update.message.reply_text(response_text, parse_mode="Markdown")

async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming voice notes. Downloads the .ogg file and forwards it to Gemini.
    """
    chat_id = update.effective_chat.id
    voice = update.message.voice
    
    # Send "record_voice" action to show the bot is listening
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Download file
    file_id = voice.file_id
    new_file = await context.bot.get_file(file_id)
    file_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_{file_id}.ogg")
    await new_file.download_to_drive(file_path)
    
    logger.info(f"Downloaded voice note from {chat_id} to {file_path}")
    
    # Pass to Gemini agent
    agent = FinancialAgent(chat_id)
    try:
        response_text = agent.chat(user_msg=update.message.caption or "", audio_path=file_path)
    finally:
        # Clean up local file
        if os.path.exists(file_path):
            os.remove(file_path)
            
    await update.message.reply_text(response_text, parse_mode="Markdown")

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming document files (PDFs, Excel sheets, text files).
    """
    chat_id = update.effective_chat.id
    document = update.message.document
    caption = update.message.caption or "Analyze this uploaded document."
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Download document
    file_id = document.file_id
    new_file = await context.bot.get_file(file_id)
    file_name = document.file_name or "document"
    file_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_{file_id}_{file_name}")
    await new_file.download_to_drive(file_path)
    
    logger.info(f"Downloaded document from {chat_id} to {file_path}")
    
    # Process document
    extracted_context = process_uploaded_document(file_path)
    
    # If the file format is supported and extracted text is returned
    agent = FinancialAgent(chat_id)
    try:
        if not extracted_context.startswith("Unsupported file format") and not extracted_context.startswith("Error"):
            response_text = agent.chat(user_msg=caption, file_context=extracted_context)
        else:
            # Try to upload directly to Gemini using the Files API (supports PDFs natively)
            # Gemini file upload supports PDF
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.pdf':
                logger.info(f"Uploading PDF file {file_path} to Gemini...")
                uploaded_file = genai.upload_file(path=file_path, mime_type="application/pdf")
                response_text = agent.chat(user_msg=caption, file_context=f"Refer to the attached document: {uploaded_file.name}")
            else:
                response_text = extracted_context # Return the error message
    finally:
        # Clean up local file
        if os.path.exists(file_path):
            os.remove(file_path)
            
    await update.message.reply_text(response_text, parse_mode="Markdown")

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle incoming photos (spreadsheets, chart screenshots, etc.).
    """
    chat_id = update.effective_chat.id
    photo = update.message.photo[-1] # Get highest resolution
    caption = update.message.caption or "Analyze this image."
    
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    
    # Download photo
    file_id = photo.file_id
    new_file = await context.bot.get_file(file_id)
    file_path = os.path.join(DOWNLOAD_DIR, f"{chat_id}_{file_id}.jpg")
    await new_file.download_to_drive(file_path)
    
    logger.info(f"Downloaded photo from {chat_id} to {file_path}")
    
    # Upload photo to Gemini using the Files API
    agent = FinancialAgent(chat_id)
    try:
        logger.info(f"Uploading image file {file_path} to Gemini...")
        uploaded_file = genai.upload_file(path=file_path, mime_type="image/jpeg")
        
        # In Gemini API, we can pass the uploaded file reference in the parts
        system_instruction = agent._get_system_instructions()
        tools = agent._get_tools()
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            tools=tools,
            system_instruction=system_instruction
        )
        
        # Load conversation history
        history = database.get_chat_history(chat_id, limit=15)
        gemini_history = []
        for h in history:
            role = 'user' if h['role'] == 'user' else 'model'
            gemini_history.append({'role': role, 'parts': [h['message']]})
            
        chat_session = model.start_chat(history=gemini_history, enable_automatic_function_calling=True)
        
        # Send photo and caption
        response = chat_session.send_message([uploaded_file, caption])
        response_text = response.text
        
        # Save chat messages
        database.add_chat_message(chat_id, 'user', f"[Sent Image] {caption}")
        database.add_chat_message(chat_id, 'assistant', response_text)
    finally:
        # Clean up local file
        if os.path.exists(file_path):
            os.remove(file_path)
            
    await update.message.reply_text(response_text, parse_mode="Markdown")
