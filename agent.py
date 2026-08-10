import os
import json
import logging
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL, GROK_API_KEY, GROK_MODEL
import database
from tools.market_tools import (
    get_stock_price, get_company_financials, get_company_news, get_market_indices,
    get_sec_filings, get_earnings_calendar, get_economic_calendar
)
from tools.web_tools import search_web, search_financial_news
from tools.google_tools import (
    list_calendar_events, create_calendar_event, search_gmail, read_google_sheet,
    generate_google_auth_url, check_google_connection, write_google_sheet,
    get_email_details, search_google_drive, read_google_drive_file
)

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
        verticals = prefs.get('verticals', ['Finance'])
        briefing_time = prefs.get('briefing_time', 'Not scheduled')
        evening_briefing_time = prefs.get('evening_briefing_time', 'Not scheduled')
        timezone = prefs.get('timezone', 'Asia/Kolkata')
        onboarding_status = self.user_profile.get('onboarding_status', 'not_started')
        google_status = "Connected" if check_google_connection(self.chat_id) else "Disconnected"

        # Load long-term memories
        memories = database.get_user_memories(self.chat_id)
        memories_str = ""
        if memories:
            memories_str = "\n".join([f"- {m['memory_text']} (ID: {m['id']}, Saved: {m['timestamp']})" for m in memories])
        else:
            memories_str = "- No long-term preferences recorded yet."

        system_prompt = f"""
You are the **Atlas Financial Assistant**, a world-class financial analyst and executive assistant.
You help {name}, who is a {role}, manage their portfolio, research markets, draft schedules, and check emails.

Current user configuration:
- Watchlist: {watchlist}
- Preferred Verticals/Domains: {verticals}
- Daily Morning Briefing: {briefing_time} ({timezone})
- Daily Evening Closing Briefing: {evening_briefing_time} ({timezone})
- Google Workspace: {google_status}
- Onboarding Status: {onboarding_status}

Learned user context / long-term preferences:
{memories_str}

### Guidelines:
1. **Be Conversational, Not Command-Driven:** Never instruct the user to use commands. Communicate naturally like an elite human analyst.
2. **Conciseness & Scannability:** Write dense, high-impact bulleted messages. Always explain **why** something matters (market implications, thesis, driver) rather than just listing numbers or headlines. Never write long essays that require massive scrolling.
3. **Onboarding Guidance:** 
   - If Onboarding Status is 'not_started' or 'started', guide the user through a quick setup:
     * Step 1: Ask what best describes their professional role.
     * Step 2: Ask what stocks/companies they want to track on their watchlist.
     * Step 3: Ask if they want to connect their Google Account (suggest using the `get_google_auth_link` tool).
     * Step 4: Ask if they want a scheduled morning and/or evening briefing (and what timezone/time).
   - Keep onboarding conversational. Let them skip any step. Use tools to save details as they mention them (e.g., `update_watchlist`, `update_profile`). 
   - Once onboarding details are captured or skipped, inform them onboarding is complete and call `update_profile(onboarding_status='completed')`.
4. **Vertical/Domain Adaptation:** You support auxiliary verticals (Investing, Tech, Startup Ecosystem, Technology, Healthcare, Education, Research, Legal, Productivity, Business) beyond primary finance. Tailor your terminology, market scans, and news queries to focus on the user's preferred verticals.
5. **Memory Management:** If you learn new preferences, watchlists, workflows, preferred schedules, or long-term details about the user during conversation, use the `store_user_memory` tool to persist them. They will automatically be loaded into your future instructions.
6. **Alerts Management:** You can set custom price alerts or percentage movement alert triggers for stocks using the `set_custom_alert` tool (e.g. crossing above a price, dropping below, or moving by a daily percentage).
7. **Research & Context:** If the user's query is vague, ask follow-up questions to understand if they want financials, news, stock trends, or due diligence.
8. **Data Sourcing:** Use tools for real-time data. Cite facts. If uncertain, state it clearly.
9. **Task Automation:** Use Google Workspace tools to view calendars, schedule meetings, search emails, or read sheets as requested.
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

        def write_google_sheet_tool(spreadsheet_id: str, range_name: str, values: list) -> str:
            """Write or update values in a Google Sheet range (values is a nested list, e.g. [[row1_val1, row1_val2], [row2_val1, ...]])."""
            return write_google_sheet(self.chat_id, spreadsheet_id, range_name, values)

        def get_email_details_tool(message_id: str) -> str:
            """Retrieve the full body content of a specific email using its message ID."""
            return get_email_details(self.chat_id, message_id)

        def search_google_drive_tool(query: str, max_results: int = 5) -> str:
            """Search for files in Google Drive by name."""
            return search_google_drive(self.chat_id, query, max_results)

        def read_google_drive_file_tool(file_id: str) -> str:
            """Read and download a file from Google Drive and return its content context (supports Google Doc, PDF, Excel, CSV, TXT, etc.)."""
            return read_google_drive_file(self.chat_id, file_id)

        def list_uploaded_documents_tool() -> str:
            """List all files/documents previously uploaded by the user to their database index, containing ID, name, type, and upload date."""
            docs = database.list_user_documents(self.chat_id)
            if not docs:
                return "You have not uploaded any documents yet."
            result = "**Uploaded Documents Registry:**\n\n"
            for d in docs:
                result += f"• **{d['file_name']}** (Doc ID: `{d['id']}`)\n  Type: {d['mime_type']} | Uploaded: {d['timestamp']}\n\n"
            return result

        def read_uploaded_document_content_tool(doc_id: int) -> str:
            """Retrieve the text contents of a previously uploaded document by its database Doc ID."""
            doc = database.get_user_document_content(self.chat_id, doc_id)
            if not doc:
                return f"No document found with Doc ID {doc_id} in your workspace database."
            return f"--- Content of Stored Document: {doc['file_name']} (Doc ID: {doc_id}) ---\n\n{doc['content']}"

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

        def update_profile(role: str = None, briefing_time: str = None, evening_briefing_time: str = None, timezone: str = None, onboarding_status: str = None, verticals: list = None) -> str:
            """
            Update the user's profile details.
            role: Professional role.
            briefing_time: Standard daily morning briefing schedule (e.g., '08:00', '09:30').
            evening_briefing_time: Standard daily evening closing briefing schedule (e.g., '17:30', '18:00').
            timezone: Preferred timezone (e.g., 'Asia/Kolkata', 'US/Eastern').
            onboarding_status: Current onboarding status ('not_started', 'started', 'completed').
            verticals: List of preferred domains/verticals (e.g., ['Technology', 'Startup Ecosystem']).
            """
            updates = {}
            if role:
                database.create_or_update_user(self.chat_id, role=role)
            if onboarding_status:
                database.create_or_update_user(self.chat_id, onboarding_status=onboarding_status)
            if briefing_time:
                updates['briefing_time'] = briefing_time
            if evening_briefing_time:
                updates['evening_briefing_time'] = evening_briefing_time
            if timezone:
                updates['timezone'] = timezone
            if verticals is not None:
                updates['verticals'] = verticals
                
            if updates:
                database.update_user_preferences(self.chat_id, updates)
                
            # Refresh local profile cache
            self.user_profile = database.get_user(self.chat_id)
            
            # Reschedule jobs in background scheduler
            prefs = self.user_profile.get('preferences', {})
            tz_str = prefs.get('timezone', 'Asia/Kolkata')
            b_time = prefs.get('briefing_time')
            eb_time = prefs.get('evening_briefing_time')
            
            import scheduler
            if b_time:
                scheduler.schedule_user_briefing(self.chat_id, b_time, tz_str)
            if eb_time:
                scheduler.schedule_user_evening_briefing(self.chat_id, eb_time, tz_str)
                
            return "Profile updated successfully."

        def set_custom_alert_tool(ticker: str, alert_type: str, target_value: float, condition: str) -> str:
            """
            Create a custom stock price alert or percentage movement trigger.
            ticker: Stock symbol (e.g. AAPL)
            alert_type: 'price' (level threshold) or 'percentage' (daily percentage change)
            target_value: Numeric value (e.g. 150.0 for price, 5.0 for a 5% percentage shift)
            condition: 'above' (trigger if value >= target), 'below' (trigger if value <= target), or 'movement' (percentage absolute shift trigger)
            """
            alert_id = database.create_user_alert(self.chat_id, ticker, alert_type, target_value, condition)
            return f"Successfully created alert for {ticker.upper()} (Alert ID: {alert_id}). Type: {alert_type} | Target: {target_value} | Condition: {condition}"

        def list_custom_alerts_tool() -> str:
            """List all your active and triggered stock alerts."""
            alerts = database.list_user_alerts(self.chat_id)
            if not alerts:
                return "You have no custom stock alerts scheduled."
            result = "**Your Custom Stock Alerts:**\n\n"
            for a in alerts:
                status = "🔴 Triggered" if a['triggered'] == 1 else "🟢 Active"
                result += f"• **{a['ticker']}** (Alert ID: `{a['id']}`)\n  Status: {status} | Type: {a['alert_type']} | Target: {a['target_value']} | Condition: {a['condition']} | Created: {a['timestamp']}\n\n"
            return result

        def delete_custom_alert_tool(alert_id: int) -> str:
            """Delete a custom stock price/percentage alert by its Alert ID."""
            database.delete_user_alert(self.chat_id, alert_id)
            return f"Alert {alert_id} has been deleted."

        def store_user_memory_tool(memory_text: str) -> str:
            """Save long-term preference facts, workflows, or insights about the user to their profile memory bank."""
            mem_id = database.add_user_memory(self.chat_id, memory_text)
            return f"Successfully saved to profile memory: '{memory_text}' (Memory ID: {mem_id})."

        def delete_user_memory_tool(memory_id: int) -> str:
            """Delete a recorded long-term preference note by its Memory ID."""
            database.delete_user_memory(self.chat_id, memory_id)
            return f"Memory {memory_id} deleted."

        # Assign natural names so Gemini recognizes them properly
        list_calendar_events_tool.__name__ = "list_calendar_events"
        create_calendar_event_tool.__name__ = "create_calendar_event"
        search_emails_tool.__name__ = "search_emails"
        read_google_sheet_tool.__name__ = "read_google_sheet"
        write_google_sheet_tool.__name__ = "write_google_sheet"
        get_email_details_tool.__name__ = "get_email_details"
        search_google_drive_tool.__name__ = "search_google_drive"
        read_google_drive_file_tool.__name__ = "read_google_drive_file"
        list_uploaded_documents_tool.__name__ = "list_uploaded_documents"
        read_uploaded_document_content_tool.__name__ = "read_uploaded_document_content"
        get_google_auth_link.__name__ = "get_google_auth_link"
        update_watchlist.__name__ = "update_watchlist"
        update_profile.__name__ = "update_profile"
        set_custom_alert_tool.__name__ = "set_custom_alert"
        list_custom_alerts_tool.__name__ = "list_custom_alerts"
        delete_custom_alert_tool.__name__ = "delete_custom_alert"
        store_user_memory_tool.__name__ = "store_user_memory"
        delete_user_memory_tool.__name__ = "delete_user_memory"

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
            write_google_sheet_tool,
            get_email_details_tool,
            search_google_drive_tool,
            read_google_drive_file_tool,
            list_uploaded_documents_tool,
            read_uploaded_document_content_tool,
            get_sec_filings,
            get_earnings_calendar,
            get_economic_calendar,
            set_custom_alert_tool,
            list_custom_alerts_tool,
            delete_custom_alert_tool,
            store_user_memory_tool,
            delete_user_memory_tool,
            get_google_auth_link,
            update_watchlist,
            update_profile
        ]

    def _chat_gemini(self, user_msg: str, file_context: str = None, audio_path: str = None, image_path: str = None) -> str:
        """
        Internal dispatcher for Gemini model.
        """
        logger.info(f"Routing query to Gemini for chat_id {self.chat_id}")
        history = database.get_chat_history(self.chat_id, limit=15)
        system_instruction = self._get_system_instructions()
        tools = self._get_tools()
        
        model_name = GEMINI_MODEL
        try:
            model = genai.GenerativeModel(
                model_name=model_name,
                tools=tools,
                system_instruction=system_instruction
            )
            
            gemini_history = []
            for h in history[:-1]:
                role = 'user' if h['role'] == 'user' else 'model'
                message_text = h['message']
                # Clean up the fallback prefix if it was saved in history
                if message_text.startswith("⚠️ *Grok API failed, fell back to Gemini:*"):
                    parts = message_text.split("\n\n", 1)
                    if len(parts) > 1:
                        message_text = parts[1]
                gemini_history.append({
                    'role': role,
                    'parts': [message_text]
                })
                
            chat_session = model.start_chat(history=gemini_history, enable_automatic_function_calling=True)
            
            parts = []
            if audio_path and os.path.exists(audio_path):
                logger.info(f"Uploading audio file {audio_path} to Gemini...")
                uploaded_file = genai.upload_file(path=audio_path, mime_type="audio/ogg")
                parts.append(uploaded_file)
                if user_msg:
                    parts.append(user_msg)
                else:
                    parts.append("Respond to this voice message.")
            elif image_path and os.path.exists(image_path):
                logger.info(f"Uploading image file {image_path} to Gemini...")
                uploaded_file = genai.upload_file(path=image_path, mime_type="image/jpeg")
                parts.append(uploaded_file)
                parts.append(user_msg or "Analyze this image.")
            else:
                msg_content = user_msg
                if file_context:
                    msg_content = f"{file_context}\n\nUser Query: {user_msg}"
                parts.append(msg_content)
                
            response = chat_session.send_message(parts)
            return response.text
            
        except Exception as e:
            # Check if it was a model not found / resource not found error
            if model_name != "gemini-1.5-flash" and ("not found" in str(e).lower() or "404" in str(e) or "no longer available" in str(e).lower() or "not available" in str(e).lower()):
                logger.warning(f"Configured Gemini model '{model_name}' failed with: {e}. Falling back to default 'gemini-1.5-flash'...")
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    tools=tools,
                    system_instruction=system_instruction
                )
                
                gemini_history = []
                for h in history[:-1]:
                    role = 'user' if h['role'] == 'user' else 'model'
                    message_text = h['message']
                    # Clean up the fallback prefix if it was saved in history
                    if message_text.startswith("⚠️ *Grok API failed, fell back to Gemini:*"):
                        parts = message_text.split("\n\n", 1)
                        if len(parts) > 1:
                            message_text = parts[1]
                    gemini_history.append({
                        'role': role,
                        'parts': [message_text]
                    })
                    
                chat_session = model.start_chat(history=gemini_history, enable_automatic_function_calling=True)
                
                parts = []
                if audio_path and os.path.exists(audio_path):
                    logger.info(f"Uploading audio file {audio_path} to Gemini...")
                    uploaded_file = genai.upload_file(path=audio_path, mime_type="audio/ogg")
                    parts.append(uploaded_file)
                    if user_msg:
                        parts.append(user_msg)
                    else:
                        parts.append("Respond to this voice message.")
                elif image_path and os.path.exists(image_path):
                    logger.info(f"Uploading image file {image_path} to Gemini...")
                    uploaded_file = genai.upload_file(path=image_path, mime_type="image/jpeg")
                    parts.append(uploaded_file)
                    parts.append(user_msg or "Analyze this image.")
                else:
                    msg_content = user_msg
                    if file_context:
                        msg_content = f"{file_context}\n\nUser Query: {user_msg}"
                    parts.append(msg_content)
                    
                response = chat_session.send_message(parts)
                return response.text
            else:
                raise e

    def chat(self, user_msg: str, file_context: str = None, audio_path: str = None, image_path: str = None) -> str:
        """
        Main interface to process user inputs and returns responses.
        Routes to Grok if GROK_API_KEY is configured, otherwise routes to Gemini.
        If Grok is configured but fails, automatically falls back to Gemini.
        """
        # Save user message to database
        database.add_chat_message(self.chat_id, 'user', user_msg)
        
        # Route to Grok if key is configured
        if GROK_API_KEY:
            logger.info(f"Routing query to Grok for chat_id {self.chat_id}")
            
            # If audio path is supplied, try to transcribe it using Gemini's lighter model first
            if audio_path and os.path.exists(audio_path):
                try:
                    logger.info("Transcribing voice note using Gemini for Grok routing...")
                    transcribe_model = genai.GenerativeModel(model_name="gemini-2.0-flash-lite")
                    uploaded_file = genai.upload_file(path=audio_path, mime_type="audio/ogg")
                    transcribe_res = transcribe_model.generate_content(
                        [uploaded_file, "Please transcribe this audio exactly. Do not add any other comment or greeting."]
                    )
                    transcription = transcribe_res.text
                    user_msg = f"[Transcribed Voice Note] {transcription}\n{user_msg}" if user_msg else f"[Transcribed Voice Note] {transcription}"
                except Exception as e:
                    logger.warning(f"Voice note transcription failed: {e}")
                    user_msg = f"[Uploaded Audio Note - Transcription unavailable: {str(e)}]\n{user_msg}" if user_msg else "[Uploaded Audio Note - Transcription unavailable]"
            
            try:
                response_text = self._chat_grok(user_msg, file_context, image_path)
                database.add_chat_message(self.chat_id, 'assistant', response_text)
                return response_text
            except Exception as e:
                logger.warning(f"Grok API call failed: {e}. Falling back to Gemini...")
                try:
                    gemini_response = self._chat_gemini(user_msg, file_context, audio_path, image_path)
                    error_note = f"⚠️ *Grok API failed, fell back to Gemini:* {str(e)}\n\n"
                    full_response = error_note + gemini_response
                    database.add_chat_message(self.chat_id, 'assistant', full_response)
                    return full_response
                except Exception as ex:
                    logger.error(f"Both Grok and Gemini APIs failed: {ex}")
                    error_msg = f"Sorry, I encountered an issue processing that. Both Grok and Gemini APIs failed. (Grok: {str(e)} | Gemini: {str(ex)})"
                    database.add_chat_message(self.chat_id, 'assistant', error_msg)
                    return error_msg

        # Otherwise route to Gemini
        try:
            response_text = self._chat_gemini(user_msg, file_context, audio_path, image_path)
            database.add_chat_message(self.chat_id, 'assistant', response_text)
            return response_text
        except Exception as e:
            logger.error(f"Error calling Gemini API for {self.chat_id}: {e}")
            error_msg = f"Sorry, I encountered an issue processing that. Please check your credentials or try again later. (Error: {str(e)})"
            database.add_chat_message(self.chat_id, 'assistant', error_msg)
            return error_msg

    def _chat_grok(self, user_msg: str, file_context: str = None, image_path: str = None) -> str:
        """
        OpenAI-compatible request dispatcher for xAI Grok-2, implementing loop-based tool calls.
        """
        import requests
        import base64
        
        system_instruction = self._get_system_instructions()
        tools_list = self._get_tools()
        tools_map = {t.__name__: t for t in tools_list}
        
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_stock_price",
                    "description": "Get current stock price, change, percent change, daily range, and volume for a ticker.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Stock symbol (e.g. AAPL)"}
                        },
                        "required": ["ticker"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_company_financials",
                    "description": "Get key financial metrics, revenue, EBITDA, margins, ratios, and growth rates.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Stock symbol (e.g. NVDA)"}
                        },
                        "required": ["ticker"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_company_news",
                    "description": "Get recent news articles for a company.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Stock symbol (e.g. TSLA)"}
                        },
                        "required": ["ticker"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_market_indices",
                    "description": "Get performance summaries of major market indices (S&P 500, Nasdaq, Dow Jones, Russell 2000, 10Y Yield).",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Search the web for general news, macroeconomic events, and corporate actions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "max_results": {"type": "integer", "description": "Number of results to retrieve (default: 5)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_financial_news",
                    "description": "Search specifically for financial or corporate news.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Financial search query"},
                            "max_results": {"type": "integer", "description": "Number of results to retrieve (default: 5)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_calendar_events",
                    "description": "Retrieve upcoming meetings and events from your connected Google Calendar.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "max_results": {"type": "integer", "description": "Max results to return (default: 5)"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_calendar_event",
                    "description": "Schedule a meeting or calendar event. Times in ISO 8601 format (YYYY-MM-DDTHH:MM:SS), e.g., '2026-08-06T14:00:00'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string", "description": "Title of the meeting"},
                            "start_time": {"type": "string", "description": "Start time in ISO 8601 format"},
                            "end_time": {"type": "string", "description": "End time in ISO 8601 format"},
                            "description": {"type": "string", "description": "Optional description of the event"}
                        },
                        "required": ["summary", "start_time", "end_time"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_emails",
                    "description": "Search Gmail emails based on queries.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "max_results": {"type": "integer", "description": "Max results to return (default: 5)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_google_sheet",
                    "description": "Read cell values from a Google Sheet.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                            "range_name": {"type": "string", "description": "Cell range (e.g. Sheet1!A1:D20)"}
                        },
                        "required": ["spreadsheet_id", "range_name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_google_auth_link",
                    "description": "Generate a custom OAuth link to connect the user's Google Workspace account.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_watchlist",
                    "description": "Add or remove a stock ticker on the user's watchlist.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "description": "'add' or 'remove'"},
                            "ticker": {"type": "string", "description": "Stock symbol (e.g. TSLA)"}
                        },
                        "required": ["action", "ticker"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "update_profile",
                    "description": "Update the user's profile details.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "description": "Professional role"},
                            "briefing_time": {"type": "string", "description": "Daily morning briefing schedule time (e.g. '08:00', '09:30')"},
                            "evening_briefing_time": {"type": "string", "description": "Daily evening closing briefing schedule time (e.g. '17:30', '18:00')"},
                            "timezone": {"type": "string", "description": "Preferred timezone (e.g. 'Asia/Kolkata')"},
                            "onboarding_status": {"type": "string", "description": "Onboarding status ('not_started', 'started', 'completed')"},
                            "verticals": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Preferred domains/verticals (e.g. ['Technology', 'Startup Ecosystem'])"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_google_sheet",
                    "description": "Write or update values in a Google Sheet range.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "spreadsheet_id": {"type": "string", "description": "Spreadsheet ID"},
                            "range_name": {"type": "string", "description": "Cell range (e.g. Sheet1!A1:D20)"},
                            "values": {
                                "type": "array",
                                "description": "A nested list representing rows (e.g. [['Header1', 'Header2'], ['Val1', 'Val2']])",
                                "items": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            }
                        },
                        "required": ["spreadsheet_id", "range_name", "values"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_email_details",
                    "description": "Retrieve the full body content of a specific email using its message ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message_id": {"type": "string", "description": "Gmail message ID"}
                        },
                        "required": ["message_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_google_drive",
                    "description": "Search files in Google Drive by name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                            "max_results": {"type": "integer", "description": "Number of results to retrieve (default: 5)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_google_drive_file",
                    "description": "Read or download a file from Google Drive and return its content context.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_id": {"type": "string", "description": "Google Drive file ID"}
                        },
                        "required": ["file_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_uploaded_documents",
                    "description": "List all files/documents previously uploaded by the user to their database index, containing ID, name, type, and upload date.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "read_uploaded_document_content",
                    "description": "Retrieve the text contents of a previously uploaded document by its database Doc ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doc_id": {"type": "integer", "description": "Database Doc ID"}
                        },
                        "required": ["doc_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_sec_filings",
                    "description": "Get recent SEC filings (10-K, 10-Q, 8-K) for a company using web search.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Stock symbol (e.g. AAPL)"}
                        },
                        "required": ["ticker"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_earnings_calendar",
                    "description": "Get upcoming earnings release dates.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Optional stock symbol (e.g. MSFT)"}
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_economic_calendar",
                    "description": "Get major macroeconomic events (CPI, GDP, interest rate decisions) scheduled for this week.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "set_custom_alert",
                    "description": "Create a custom stock price alert or percentage movement trigger.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "description": "Stock symbol (e.g. AAPL)"},
                            "alert_type": {"type": "string", "description": "'price' or 'percentage'"},
                            "target_value": {"type": "number", "description": "Numeric value (e.g. 150.0 or 5.0 for a 5% shift)"},
                            "condition": {"type": "string", "description": "'above', 'below', or 'movement'"}
                        },
                        "required": ["ticker", "alert_type", "target_value", "condition"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_custom_alerts",
                    "description": "List all your active and triggered stock alerts.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_custom_alert",
                    "description": "Delete a custom stock price/percentage alert by its Alert ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "alert_id": {"type": "integer", "description": "Alert database ID"}
                        },
                        "required": ["alert_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "store_user_memory",
                    "description": "Save long-term preference facts, workflows, or insights about the user to their profile memory bank.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "memory_text": {"type": "string", "description": "Preference statement to memorize about the user"}
                        },
                        "required": ["memory_text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_user_memory",
                    "description": "Delete a recorded long-term preference note by its Memory ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "memory_id": {"type": "integer", "description": "Memory database ID"}
                        },
                        "required": ["memory_id"]
                    }
                }
            }
        ]
        
        # Load conversation history from DB
        history = database.get_chat_history(self.chat_id, limit=15)
        
        # Build messages payload
        messages = [{"role": "system", "content": system_instruction}]
        
        # Add past conversations
        for h in history[:-1]:
            messages.append({
                "role": "user" if h["role"] == "user" else "assistant",
                "content": h["message"]
            })
            
        # Format current request
        latest_content = []
        text_part = user_msg or "Respond to my query."
        if file_context:
            text_part = f"{file_context}\n\nUser Query: {user_msg}"
            
        latest_content.append({"type": "text", "text": text_part})
        
        # Add base64 image if uploaded
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                latest_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{encoded_string}"
                    }
                })
                logger.info("Successfully appended visual image content for Grok.")
            except Exception as e:
                logger.error(f"Failed to encode image for Grok: {e}")
                
        messages.append({"role": "user", "content": latest_content})
        
        # Check if it's an OpenRouter key or standard xAI key
        is_openrouter = GROK_API_KEY.startswith("sk-or-")
        
        if is_openrouter:
            url = "https://openrouter.ai/api/v1/chat/completions"
            active_model = "meta-llama/llama-3.1-8b-instruct:free"  # Stable default fallback
            headers = {
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://atlas-ai-financial-assistant.onrender.com",
                "X-Title": "Atlas Financial Assistant"
            }
            logger.info("OpenRouter key detected. Resolving active free model...")
            try:
                models_resp = requests.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {GROK_API_KEY}"}, timeout=10)
                if models_resp.status_code == 200:
                    model_ids = [m["id"] for m in models_resp.json().get("data", [])]
                    free_models = [mid for mid in model_ids if mid.endswith(":free")]
                    if free_models:
                        # Prefer llama-3.1-8b or gemma-2-9b for tool calling
                        preferred = None
                        for fm in free_models:
                            if "llama-3.1-8b" in fm.lower() or "gemma-2-9b" in fm.lower():
                                preferred = fm
                                break
                        active_model = preferred if preferred else free_models[0]
                        logger.info(f"Dynamically resolved OpenRouter model: {active_model} (All free: {free_models})")
            except Exception as e:
                logger.error(f"Failed to query OpenRouter free models: {e}")
        else:
            url = "https://api.x.ai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            # Resolve active Grok model dynamically from user's API Key allowed models list
            active_model = GROK_MODEL
            try:
                models_url = "https://api.x.ai/v1/models"
                models_headers = {"Authorization": f"Bearer {GROK_API_KEY}"}
                models_resp = requests.get(models_url, headers=models_headers, timeout=10)
                if models_resp.status_code == 200:
                    models_data = models_resp.json()
                    model_ids = [m["id"] for m in models_data.get("data", [])]
                    if model_ids:
                        if GROK_MODEL not in model_ids:
                            fallback = None
                            for mid in model_ids:
                                # Prefer non-vision, non-image grok models
                                if "grok" in mid.lower() and "vision" not in mid.lower() and "imagine" not in mid.lower():
                                    fallback = mid
                                    break
                            if not fallback:
                                for mid in model_ids:
                                    if "grok" in mid.lower():
                                        fallback = mid
                                        break
                            if not fallback:
                                fallback = model_ids[0]
                            logger.info(f"Model '{GROK_MODEL}' not in key list. Falling back to active model '{fallback}' (Allowed: {model_ids})")
                            active_model = fallback
            except Exception as e:
                logger.error(f"Failed to fetch active Grok models: {e}")

        max_turns = 8
        for turn in range(max_turns):
            payload = {
                "model": active_model,
                "messages": messages,
                "tools": openai_tools,
                "tool_choice": "auto"
            }
            
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=45)
                if response.status_code != 200:
                    allowed_models = "Unable to fetch"
                    try:
                        m_resp = requests.get("https://api.x.ai/v1/models", headers={"Authorization": f"Bearer {GROK_API_KEY}"}, timeout=5)
                        if m_resp.status_code == 200:
                            allowed_models = ", ".join([m["id"] for m in m_resp.json().get("data", [])])
                        else:
                            allowed_models = f"Error {m_resp.status_code}: {m_resp.text}"
                    except Exception as ex:
                        allowed_models = f"Exception: {str(ex)}"
                        
                    logger.error(f"Grok API returned status {response.status_code}: {response.text}")
                    raise RuntimeError(
                        f"Grok API Status {response.status_code}: {response.text} (Allowed Models: {allowed_models})"
                    )
                    
                resp_json = response.json()
                choice = resp_json["choices"][0]
                message_obj = choice["message"]
                
                # Append Grok's message to context list
                # Note: xAI requires tool_calls object layout to match exactly
                messages.append(message_obj)
                
                tool_calls = message_obj.get("tool_calls")
                if not tool_calls:
                    return message_obj.get("content") or "No message content returned."
                    
                # Loop through calls
                for tc in tool_calls:
                    func_name = tc["function"]["name"]
                    func_args = json.loads(tc["function"]["arguments"])
                    call_id = tc["id"]
                    
                    logger.info(f"Grok requesting tool call: {func_name} with args {func_args}")
                    
                    if func_name in tools_map:
                        try:
                            # Execute the tool
                            res = tools_map[func_name](**func_args)
                        except Exception as e:
                            logger.error(f"Error executing local tool {func_name}: {e}")
                            res = f"Error executing tool: {str(e)}"
                    else:
                        res = f"Tool {func_name} is not supported."
                        
                    # Append result to log
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": func_name,
                        "content": str(res)
                    })
                    
            except Exception as e:
                logger.error(f"Exception during Grok API turn: {e}")
                raise e
                
        raise RuntimeError("Grok tool execution depth limit exceeded.")
