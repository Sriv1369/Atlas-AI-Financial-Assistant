import os
import json
import logging
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL
import database
from tools.market_tools import get_stock_price, get_company_financials, get_company_news, get_market_indices
from tools.web_tools import search_web, search_financial_news
from tools.google_tools import list_calendar_events, create_calendar_event, search_gmail, read_google_sheet, generate_google_auth_url, check_google_connection

logger = logging.getLogger(__name__)

# Configure Gemini SDK
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.error("GEMINI_API_KEY not found. Agent will not function correctly.")

class FinancialAgent:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.user_profile = database.get_user(chat_id)
        if not self.user_profile:
            # Create a blank user if they don't exist yet
            database.create_or_update_user(chat_id, onboarding_status='not_started')
            self.user_profile = database.get_user(chat_id)

    def _get_system_instructions(self) -> str:
        name = self.user_profile.get('name', 'there')
        role = self.user_profile.get('role', 'finance professional')
        prefs = self.user_profile.get('preferences', {})
        watchlist = prefs.get('watchlist', [])
        briefing_time = prefs.get('briefing_time', 'Not scheduled')
        timezone = prefs.get('timezone', 'Asia/Kolkata')
        onboarding_status = self.user_profile.get('onboarding_status', 'not_started')
        google_status = "Connected" if check_google_connection(self.chat_id) else "Disconnected"

        system_prompt = f"""
You are the **Atlas Financial Assistant**, a world-class financial analyst and executive assistant.
You help {name}, who is a {role}, manage their portfolio, research markets, draft schedules, and check emails.

Current user configuration:
- Watchlist: {watchlist}
- Daily Briefing: {briefing_time} ({timezone})
- Google Workspace: {google_status}
- Onboarding Status: {onboarding_status}

### Guidelines:
1. **Be Conversational, Not Command-Driven:** Never instruct the user to use commands. Communicate naturally like an elite human analyst.
2. **Conciseness & Scannability:** Write dense, high-impact bulleted messages. Always explain **why** something matters (market implications, thesis, driver) rather than just listing numbers or headlines. Never write long essays that require massive scrolling.
3. **Onboarding Guidance:** 
   - If Onboarding Status is 'not_started' or 'started', guide the user through a quick 4-step conversational setup:
     * Step 1: Ask what best describes their professional role.
     * Step 2: Ask what stocks/companies they want to track on their watchlist.
     * Step 3: Ask if they want to connect their Google Account (suggest using the `get_google_auth_link` tool).
     * Step 4: Ask if they want a scheduled morning briefing (and what timezone/time).
   - Keep onboarding conversational. Let them skip any step. Use tools to save details as they mention them (e.g., `update_watchlist`, `update_profile`). 
   - Once onboarding details are captured or skipped, inform them onboarding is complete and call `update_profile(onboarding_status='completed')`.
4. **Research & Context:** If the user's query is vague (e.g., "tell me about Nvidia"), ask follow-up questions to understand if they want financials, news, stock trends, or due diligence.
5. **Data Sourcing:** Use tools for real-time data (`get_stock_price`, `get_company_financials`, `get_company_news`, `get_market_indices`, `search_web`). Cite facts. If uncertain, state it clearly.
6. **Task Automation:** Use Google Workspace tools to view calendars, schedule meetings, search emails, or read sheets as requested.
"""
        return system_prompt

    def _get_tools(self):
        """
        Build and return dynamic wrapper functions pre-bound with the user's chat_id.
        """
        # Dynamic tool wrappers to pass chat_id implicitly
        def list_calendar_events_tool(max_results: int = 5) -> str:
            """Retrieve upcoming meetings and events from your connected Google Calendar."""
            return list_calendar_events(self.chat_id, max_results)

        def create_calendar_event_tool(summary: str, start_time: str, end_time: str, description: str = None) -> str:
            """
            Schedule a meeting or calendar event. 
            Times should be in ISO 8601 format (YYYY-MM-DDTHH:MM:SS), e.g., '2026-08-06T14:00:00'.
            """
            return create_calendar_event(self.chat_id, summary, start_time, end_time, description)

        def search_emails_tool(query: str, max_results: int = 5) -> str:
            """Search Gmail emails based on queries (e.g. sender, company keyword, subject)."""
            return search_gmail(self.chat_id, query, max_results)

        def read_google_sheet_tool(spreadsheet_id: str, range_name: str) -> str:
            """Read cell values from a Google Sheet."""
            return read_google_sheet(self.chat_id, spreadsheet_id, range_name)

        def get_google_auth_link() -> str:
            """Generate a custom OAuth link to connect the user's Google Workspace account."""
            return f"Please link your Google account here: {generate_google_auth_url(self.chat_id)}"

        def update_watchlist(action: str, ticker: str) -> str:
            """
            Add or remove a stock ticker on the user's watchlist.
            action: 'add' or 'remove'. ticker: Stock symbol (e.g. AAPL).
            """
            action = action.lower().strip()
            ticker = ticker.upper().strip()
            prefs = self.user_profile.get('preferences', {})
            watchlist = prefs.get('watchlist', [])
            
            if action == 'add':
                if ticker not in watchlist:
                    watchlist.append(ticker)
                    database.update_user_preferences(self.chat_id, {'watchlist': watchlist})
                    # Refresh local profile cache
                    self.user_profile = database.get_user(self.chat_id)
                    return f"Added {ticker} to your watchlist."
                return f"{ticker} is already in your watchlist."
            elif action == 'remove':
                if ticker in watchlist:
                    watchlist.remove(ticker)
                    database.update_user_preferences(self.chat_id, {'watchlist': watchlist})
                    # Refresh local profile cache
                    self.user_profile = database.get_user(self.chat_id)
                    return f"Removed {ticker} from your watchlist."
                return f"{ticker} was not in your watchlist."
            return "Invalid action. Use 'add' or 'remove'."

        def update_profile(role: str = None, briefing_time: str = None, timezone: str = None, onboarding_status: str = None) -> str:
            """
            Update the user's profile details.
            role: Professional role.
            briefing_time: Standard daily briefing schedule (e.g., '08:00', '17:30').
            timezone: Preferred timezone (e.g., 'Asia/Kolkata', 'US/Eastern').
            onboarding_status: Current onboarding status ('not_started', 'started', 'completed').
            """
            updates = {}
            if role:
                database.create_or_update_user(self.chat_id, role=role)
            if onboarding_status:
                database.create_or_update_user(self.chat_id, onboarding_status=onboarding_status)
            if briefing_time:
                updates['briefing_time'] = briefing_time
            if timezone:
                updates['timezone'] = timezone
                
            if updates:
                database.update_user_preferences(self.chat_id, updates)
                
            # Refresh local profile cache
            self.user_profile = database.get_user(self.chat_id)
            return "Profile updated successfully."

        # Assign natural names so Gemini recognizes them properly
        list_calendar_events_tool.__name__ = "list_calendar_events"
        create_calendar_event_tool.__name__ = "create_calendar_event"
        search_emails_tool.__name__ = "search_emails"
        read_google_sheet_tool.__name__ = "read_google_sheet"
        get_google_auth_link.__name__ = "get_google_auth_link"
        update_watchlist.__name__ = "update_watchlist"
        update_profile.__name__ = "update_profile"

        return [
            get_stock_price,
            get_company_financials,
            get_company_news,
            get_market_indices,
            search_web,
            search_financial_news,
            list_calendar_events_tool,
            create_calendar_event_tool,
            search_emails_tool,
            read_google_sheet_tool,
            get_google_auth_link,
            update_watchlist,
            update_profile
        ]

    def chat(self, user_msg: str, file_context: str = None, audio_path: str = None) -> str:
        """
        Main interface to process user inputs and returns responses.
        Loads history, configures the Gemini generative model with tools, and manages automatic function calling.
        """
        # Save user message to database
        database.add_chat_message(self.chat_id, 'user', user_msg)
        
        # Load conversation history
        history = database.get_chat_history(self.chat_id, limit=15)
        
        # Prepare generative model
        system_instruction = self._get_system_instructions()
        tools = self._get_tools()
        
        # We use gemini-2.5-pro since it is much better at complex multi-turn reasoning and tool calling
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            tools=tools,
            system_instruction=system_instruction
        )
        
        # Convert DB history format to Gemini Chat history format
        gemini_history = []
        for h in history[:-1]: # exclude the latest user message which we will send to start the response
            role = 'user' if h['role'] == 'user' else 'model'
            gemini_history.append({
                'role': role,
                'parts': [h['message']]
            })
            
        # Start chat
        chat_session = model.start_chat(history=gemini_history, enable_automatic_function_calling=True)
        
        try:
            logger.info(f"Sending message to Gemini for chat_id {self.chat_id}")
            
            # Prepare message parts
            parts = []
            
            # If an audio voice note is uploaded
            if audio_path and os.path.exists(audio_path):
                logger.info(f"Uploading audio file {audio_path} to Gemini...")
                # Gemini SDK supports direct upload of audio
                uploaded_file = genai.upload_file(path=audio_path, mime_type="audio/ogg")
                parts.append(uploaded_file)
                # If the user also sent text alongside voice, append it
                if user_msg:
                    parts.append(user_msg)
                else:
                    parts.append("Respond to this voice message.")
            else:
                # Normal text message + optional document text attachment
                msg_content = user_msg
                if file_context:
                    msg_content = f"{file_context}\n\nUser Query: {user_msg}"
                parts.append(msg_content)
                
            response = chat_session.send_message(parts)
            response_text = response.text
            
            # Save assistant response to DB
            database.add_chat_message(self.chat_id, 'assistant', response_text)
            return response_text
            
        except Exception as e:
            logger.error(f"Error calling Gemini API for {self.chat_id}: {e}")
            error_msg = f"Sorry, I encountered an issue processing that. Please check your credentials or try again later. (Error: {str(e)})"
            database.add_chat_message(self.chat_id, 'assistant', error_msg)
            return error_msg
