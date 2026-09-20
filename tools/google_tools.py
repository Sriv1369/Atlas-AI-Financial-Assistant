import json
import logging
import threading
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import datetime
import os
import io
import pandas as pd
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import google.auth.transport.requests

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_PORT
import database

logger = logging.getLogger(__name__)

# Google API Scopes required by the assistant
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/spreadsheets', # Upgraded to read/write
    'https://www.googleapis.com/auth/drive.readonly'
]

def get_google_creds(chat_id: int) -> Credentials:
    """
    Get and refresh Google credentials for a user.
    """
    creds_data = database.get_google_credentials(chat_id)
    if not creds_data:
        return None
        
    try:
        # Rebuild credentials object
        creds = Credentials(
            token=creds_data.get('token'),
            refresh_token=creds_data.get('refresh_token'),
            token_uri=creds_data.get('token_uri'),
            client_id=creds_data.get('client_id'),
            client_secret=creds_data.get('client_secret'),
            scopes=creds_data.get('scopes')
        )
        
        # Check if expired and refresh
        if creds.expired and creds.refresh_token:
            request = google.auth.transport.requests.Request()
            creds.refresh(request)
            # Save refreshed credentials
            database.save_google_credentials(chat_id, {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            })
            logger.info(f"Google credentials refreshed for user {chat_id}.")
            
        return creds
    except Exception as e:
        logger.error(f"Error restoring/refreshing Google credentials for {chat_id}: {e}")
        return None

def check_google_connection(chat_id: int) -> bool:
    """
    Check if the user is connected to Google.
    """
    return get_google_creds(chat_id) is not None

def _get_redirect_uri() -> str:
    """
    Get the OAuth redirect URI, dynamically resolving public hostname if deployed on Render or other cloud services.
    """
    public_url = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if public_url:
        url = public_url.strip()
        if not url.endswith("/"):
            url += "/"
        return url
    return f"http://localhost:{GOOGLE_REDIRECT_PORT}/"

def generate_google_auth_url(chat_id: int) -> str:
    """
    Generate Google OAuth authentication URL, passing chat_id in state.
    """
    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
        }
    }
    
    redirect_uri = _get_redirect_uri()
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    
    # We pass chat_id as the 'state' parameter to identify the user on callback
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=str(chat_id),
        prompt='consent'
    )
    
    return auth_url

# Web server request handler for Google OAuth Callback
class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress standard logging to console for OAuth hits
        return

    def do_GET(self):
        parsed_path = urlparse(self.path)
        # Handle health check requests from Render or other platforms
        if parsed_path.path in ["/", "/healthz", "/health"]:
            query_components = parse_qs(parsed_path.query)
            if "code" not in query_components or "state" not in query_components:
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Atlas callback server is active</h1><p>Health check passed.</p>")
                return

        query_components = parse_qs(parsed_path.query)
        code = query_components.get("code")
        state = query_components.get("state") # chat_id
        
        if not code or not state:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Error</h1><p>Missing authorization code or user state.</p>")
            return
            
        chat_id = int(state[0])
        auth_code = code[0]
        
        try:
            client_config = {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            }
            
            redirect_uri = _get_redirect_uri()
            flow = Flow.from_client_config(
                client_config,
                scopes=SCOPES,
                redirect_uri=redirect_uri
            )
            
            flow.fetch_token(code=auth_code)
            creds = flow.credentials
            
            # Save to SQLite
            database.save_google_credentials(chat_id, {
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
                'scopes': creds.scopes
            })
            
            # Set onboarding step or status
            user = database.get_user(chat_id)
            if user and user['onboarding_status'] != 'completed':
                database.create_or_update_user(chat_id, onboarding_status='started', onboarding_step=4) # advance state
            
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            
            success_html = """
            <html>
            <head>
                <title>Authentication Successful</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; text-align: center; padding: 50px; background-color: #f4f7f6; }
                    .card { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); display: inline-block; max-width: 500px; }
                    h1 { color: #2ecc71; }
                    p { color: #555; font-size: 16px; line-height: 1.6; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>Linked Successfully!</h1>
                    <p>Your Google Workspace accounts (Gmail, Calendar, Sheets, and Drive) are now linked to your Atlas Financial Assistant.</p>
                    <p>You can close this tab and return to Telegram to continue your workflow.</p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(success_html.encode('utf-8'))
            logger.info(f"User {chat_id} successfully linked Google Account.")
            
        except Exception as e:
            logger.error(f"Error handling Google OAuth callback for user {chat_id}: {e}")
            self.send_response(500)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h1>OAuth Error</h1><p>{str(e)}</p>".encode('utf-8'))

def start_oauth_callback_server():
    """
    Starts the local redirect callback server in a daemon thread.
    """
    server_address = ('', GOOGLE_REDIRECT_PORT)
    httpd = HTTPServer(server_address, OAuthCallbackHandler)
    logger.info(f"OAuth Callback Server running on port {GOOGLE_REDIRECT_PORT}...")
    
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    return httpd

# --- Google API Tools for the Agent ---

def list_calendar_events(chat_id: int, max_results: int = 5) -> str:
    """
    Retrieve upcoming meetings and events from Google Calendar.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google account' to link it."
        
    try:
        service = build('calendar', 'v3', credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + 'Z' # 'Z' indicates UTC time
        
        events_result = service.events().list(
            calendarId='primary', 
            timeMin=now,
            maxResults=max_results, 
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        if not events:
            return "No upcoming meetings or events found in your Google Calendar."
            
        result = "**Upcoming Calendar Events:**\n\n"
        for event in events:
            summary = event.get('summary', 'Untitled Event')
            start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
            
            # Format time
            if 'T' in start:
                dt = datetime.datetime.fromisoformat(start.replace('Z', '+00:00'))
                time_str = dt.strftime('%A, %b %d at %I:%M %p')
            else:
                time_str = f"{start} (All day)"
                
            result += f"• **{summary}**\n  _{time_str}_\n"
            if event.get('description'):
                result += f"  Description: {event.get('description')}\n"
            result += "\n"
        return result
    except Exception as e:
        logger.error(f"Error listing calendar events for {chat_id}: {e}")
        return f"Error connecting to Google Calendar: {str(e)}"

def create_calendar_event(chat_id: int, summary: str, start_time: str, end_time: str, description: str = None) -> str:
    """
    Schedule a meeting or calendar event. 
    Times should be in ISO 8601 format (YYYY-MM-DDTHH:MM:SS), e.g., '2026-08-06T14:00:00'.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."
        
    try:
        service = build('calendar', 'v3', credentials=creds)
        
        event = {
            'summary': summary,
            'description': description or '',
            'start': {
                'dateTime': start_time,
                'timeZone': database.get_user(chat_id).get('preferences', {}).get('timezone', 'Asia/Kolkata'),
            },
            'end': {
                'dateTime': end_time,
                'timeZone': database.get_user(chat_id).get('preferences', {}).get('timezone', 'Asia/Kolkata'),
            }
        }
        
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return f"Event created successfully: **{summary}** scheduled for {start_time}."
    except Exception as e:
        logger.error(f"Error creating calendar event for {chat_id}: {e}")
        return f"Failed to schedule event: {str(e)}"

def search_gmail(chat_id: int, query: str, max_results: int = 5) -> str:
    """
    Search Gmail emails based on queries (e.g. sender, company keyword, subject).
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."
        
    try:
        service = build('gmail', 'v1', credentials=creds)
        
        # Search query execution
        results = service.users().messages().list(userId='me', q=query, maxResults=max_results).execute()
        messages = results.get('messages', [])
        
        if not messages:
            return f"No emails found matching query: '{query}'."
            
        result = f"**Gmail Search Results for '{query}':**\n\n"
        for msg in messages:
            msg_details = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['From', 'Subject', 'Date']).execute()
            headers = msg_details.get('payload', {}).get('headers', [])
            
            headers_dict = {h['name'].lower(): h['value'] for h in headers}
            sender = headers_dict.get('from', 'Unknown Sender')
            subject = headers_dict.get('subject', '(No Subject)')
            date = headers_dict.get('date', 'Unknown Date')
            snippet = msg_details.get('snippet', '')
            
            result += f"• **{subject}**\n  From: {sender}\n  Date: {date}\n  Summary: _{snippet}_\n\n"
            
        return result
    except Exception as e:
        logger.error(f"Error searching Gmail for {chat_id}: {e}")
        return f"Failed to search emails: {str(e)}"

def read_google_sheet(chat_id: int, spreadsheet_id: str, range_name: str) -> str:
    """
    Read cell values from a Google Sheet.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."
        
    try:
        service = build('sheets', 'v4', credentials=creds)
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, 
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return "No data found in the specified range."
            
        # Format as Markdown table
        df = pd.DataFrame(values[1:], columns=values[0]) if len(values) > 1 else pd.DataFrame(values)
        return f"**Data from Google Sheet ({range_name}):**\n\n{df.to_markdown(index=False)}"
    except Exception as e:
        logger.error(f"Error reading Google Sheet {spreadsheet_id} for {chat_id}: {e}")
        return f"Failed to read Google Sheet: {str(e)}"

def write_google_sheet(chat_id: int, spreadsheet_id: str, range_name: str, values: list) -> str:
    """
    Write or update values in a Google Sheet range.
    values: A list of lists representing rows (e.g. [["Header1", "Header2"], ["Row1Col1", "Row1Col2"]]).
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."
        
    try:
        service = build('sheets', 'v4', credentials=creds)
        body = {
            'values': values
        }
        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()
        updated_cells = result.get('updatedCells', 0)
        return f"Google Sheet updated successfully. Updated {updated_cells} cells in range '{range_name}'."
    except Exception as e:
        logger.error(f"Error writing to Google Sheet {spreadsheet_id} for {chat_id}: {e}")
        return f"Failed to write to Google Sheet: {str(e)}"

def get_email_details(chat_id: int, message_id: str) -> str:
    """
    Retrieve the full body content of a specific email using its message ID.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."
        
    try:
        service = build('gmail', 'v1', credentials=creds)
        msg = service.users().messages().get(userId='me', id=message_id, format='full').execute()
        
        headers = msg.get('payload', {}).get('headers', [])
        headers_dict = {h['name'].lower(): h['value'] for h in headers}
        sender = headers_dict.get('from', 'Unknown Sender')
        subject = headers_dict.get('subject', '(No Subject)')
        date = headers_dict.get('date', 'Unknown Date')
        
        # Extract body text from the message parts
        body = ""
        payload = msg.get('payload', {})
        
        def extract_body_parts(part):
            text_body = ""
            mime_type = part.get('mimeType', '')
            body_data = part.get('body', {}).get('data', '')
            
            if mime_type == 'text/plain' and body_data:
                import base64
                try:
                    text_body += base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                except Exception:
                    pass
            elif 'parts' in part:
                for subpart in part['parts']:
                    text_body += extract_body_parts(subpart)
            return text_body
            
        if 'parts' in payload:
            for part in payload['parts']:
                body += extract_body_parts(part)
        else:
            body_data = payload.get('body', {}).get('data', '')
            if body_data:
                import base64
                try:
                    body = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                except Exception:
                    pass
                    
        if not body.strip():
            body = msg.get('snippet', '')
            
        result = (
            f"**Email Details:**\n"
            f"• **From:** {sender}\n"
            f"• **Subject:** {subject}\n"
            f"• **Date:** {date}\n"
            f"• **ID:** `{message_id}`\n\n"
            f"--- Body ---\n"
            f"{body[:4000]}"
        )
        if len(body) > 4000:
            result += "\n\n[Truncated: Email body exceeds 4,000 characters]"
        return result
    except Exception as e:
        logger.error(f"Error fetching email {message_id} for {chat_id}: {e}")
        return f"Failed to retrieve email details: {str(e)}"

def search_google_drive(chat_id: int, query: str, max_results: int = 5) -> str:
    """
    Search files in Google Drive by name.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."
        
    try:
        service = build('drive', 'v3', credentials=creds)
        # Escape single quotes in search query
        safe_query = query.replace("'", "\\'")
        q_str = f"name contains '{safe_query}' and trashed = false"
        
        results = service.files().list(
            q=q_str,
            pageSize=max_results,
            fields="files(id, name, mimeType)"
        ).execute()
        
        files = results.get('files', [])
        if not files:
            return f"No Google Drive files found matching query: '{query}'."
            
        result = f"**Google Drive Search Results for '{query}':**\n\n"
        for f in files:
            result += f"• **{f['name']}**\n  ID: `{f['id']}` | Type: `{f['mimeType']}`\n\n"
        return result
    except Exception as e:
        logger.error(f"Error searching Google Drive for {chat_id}: {e}")
        return f"Failed to search Google Drive: {str(e)}"

def read_google_drive_file(chat_id: int, file_id: str) -> str:
    """
    Read or download a file from Google Drive and return its content context.
    """
    creds = get_google_creds(chat_id)
    if not creds:
        return "Your Google account is not connected. Type 'connect google' to link it."
        
    try:
        service = build('drive', 'v3', credentials=creds)
        file_metadata = service.files().get(fileId=file_id).execute()
        name = file_metadata.get('name', 'downloaded_file')
        mime_type = file_metadata.get('mimeType', '')
        
        # Google Docs require exporting, binary files require direct downloading
        if mime_type == 'application/vnd.google-apps.document':
            request = service.files().export_media(fileId=file_id, mimeType='text/plain')
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            content = fh.getvalue().decode('utf-8', errors='ignore')
            return f"--- Google Doc: {name} ---\n\n{content[:50000]}"
            
        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            return f"This file '{name}' is a Google Spreadsheet. Please use the `read_google_sheet` tool with range details (e.g. Sheet1!A1:D20) to view its contents."
            
        else:
            # Download binary/text file
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
                
            # Write bytes to a local temporary file to run process_uploaded_document
            temp_dir = "downloads"
            os.makedirs(temp_dir, exist_ok=True)
            ext = os.path.splitext(name)[1].lower()
            temp_path = os.path.join(temp_dir, f"gdrive_{chat_id}_{file_id}{ext}")
            
            with open(temp_path, 'wb') as f:
                f.write(fh.getvalue())
                
            try:
                from tools.document_tools import process_uploaded_document
                extracted_text = process_uploaded_document(temp_path)
                return extracted_text
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
    except Exception as e:
        logger.error(f"Error reading Google Drive file {file_id} for {chat_id}: {e}")
        return f"Failed to read Google Drive file: {str(e)}"
