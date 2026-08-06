import sqlite3
import json
import logging
from datetime import datetime
from config import DATABASE_PATH

logger = logging.getLogger(__name__)

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        name TEXT,
        onboarding_status TEXT DEFAULT 'not_started',
        role TEXT,
        preferences TEXT, -- JSON string
        onboarding_step INTEGER DEFAULT 0
    )
    """)
    
    # Create Conversations Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        timestamp TEXT,
        role TEXT, -- 'user', 'assistant'
        message TEXT,
        FOREIGN KEY(chat_id) REFERENCES users(chat_id)
    )
    """)
    
    # Create Google Credentials Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS google_credentials (
        chat_id INTEGER PRIMARY KEY,
        credentials TEXT, -- JSON string of serialized credentials
        FOREIGN KEY(chat_id) REFERENCES users(chat_id)
    )
    """)
    
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

# User Helper Functions
def get_user(chat_id):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    if user:
        user_dict = dict(user)
        if user_dict.get('preferences'):
            try:
                user_dict['preferences'] = json.loads(user_dict['preferences'])
            except json.JSONDecodeError:
                user_dict['preferences'] = {}
        else:
            user_dict['preferences'] = {}
        return user_dict
    return None

def create_or_update_user(chat_id, name=None, onboarding_status='not_started', role=None, preferences=None, onboarding_step=0):
    conn = get_db_connection()
    pref_str = json.dumps(preferences) if preferences is not None else json.dumps({})
    
    user = get_user(chat_id)
    if user:
        # Update existing user
        conn.execute("""
        UPDATE users 
        SET name = COALESCE(?, name), 
            onboarding_status = ?, 
            role = COALESCE(?, role), 
            preferences = ?,
            onboarding_step = ?
        WHERE chat_id = ?
        """, (name, onboarding_status, role, pref_str, onboarding_step, chat_id))
    else:
        # Create new user
        conn.execute("""
        INSERT INTO users (chat_id, name, onboarding_status, role, preferences, onboarding_step)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, name, onboarding_status, role, pref_str, onboarding_step))
        
    conn.commit()
    conn.close()

def update_user_preferences(chat_id, updates):
    user = get_user(chat_id)
    if not user:
        return
    prefs = user['preferences'] or {}
    prefs.update(updates)
    
    conn = get_db_connection()
    conn.execute("UPDATE users SET preferences = ? WHERE chat_id = ?", (json.dumps(prefs), chat_id))
    conn.commit()
    conn.close()

# Chat History Helper Functions
def get_chat_history(chat_id, limit=20):
    conn = get_db_connection()
    rows = conn.execute("""
    SELECT role, message, timestamp 
    FROM conversations 
    WHERE chat_id = ? 
    ORDER BY id DESC LIMIT ?
    """, (chat_id, limit)).fetchall()
    conn.close()
    
    # Reverse to restore chronological order
    history = [dict(row) for row in reversed(rows)]
    return history

def add_chat_message(chat_id, role, message):
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    conn.execute("""
    INSERT INTO conversations (chat_id, timestamp, role, message)
    VALUES (?, ?, ?, ?)
    """, (chat_id, timestamp, role, message))
    conn.commit()
    conn.close()

# Google Credentials Helper Functions
def save_google_credentials(chat_id, creds_dict):
    conn = get_db_connection()
    creds_str = json.dumps(creds_dict)
    conn.execute("""
    INSERT OR REPLACE INTO google_credentials (chat_id, credentials)
    VALUES (?, ?)
    """, (chat_id, creds_str))
    conn.commit()
    conn.close()

def get_google_credentials(chat_id):
    conn = get_db_connection()
    row = conn.execute("SELECT credentials FROM google_credentials WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row['credentials'])
        except json.JSONDecodeError:
            return None
    return None

def delete_google_credentials(chat_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM google_credentials WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
