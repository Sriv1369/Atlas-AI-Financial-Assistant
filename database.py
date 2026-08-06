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
    
    # Create User Documents Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        file_name TEXT,
        mime_type TEXT,
        content TEXT,
        timestamp TEXT,
        FOREIGN KEY(chat_id) REFERENCES users(chat_id)
    )
    """)
    
    # Create User Alerts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        ticker TEXT,
        alert_type TEXT, -- 'percentage' or 'price'
        target_value REAL,
        condition TEXT, -- 'above', 'below', 'movement'
        triggered INTEGER DEFAULT 0,
        timestamp TEXT,
        FOREIGN KEY(chat_id) REFERENCES users(chat_id)
    )
    """)
    
    # Create User Memories Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        memory_text TEXT,
        timestamp TEXT,
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

# User Documents Helper Functions
def save_user_document(chat_id: int, file_name: str, mime_type: str, content: str) -> int:
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO user_documents (chat_id, file_name, mime_type, content, timestamp)
    VALUES (?, ?, ?, ?, ?)
    """, (chat_id, file_name, mime_type, content, timestamp))
    doc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return doc_id

def list_user_documents(chat_id: int):
    conn = get_db_connection()
    rows = conn.execute("""
    SELECT id, file_name, mime_type, timestamp 
    FROM user_documents 
    WHERE chat_id = ? 
    ORDER BY id DESC
    """, (chat_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_user_document_content(chat_id: int, doc_id: int):
    conn = get_db_connection()
    row = conn.execute("""
    SELECT file_name, content 
    FROM user_documents 
    WHERE chat_id = ? AND id = ?
    """, (chat_id, doc_id)).fetchone()
    conn.close()
    return dict(row) if row else None

# User Alerts Helper Functions
def create_user_alert(chat_id: int, ticker: str, alert_type: str, target_value: float, condition: str) -> int:
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO user_alerts (chat_id, ticker, alert_type, target_value, condition, triggered, timestamp)
    VALUES (?, ?, ?, ?, ?, 0, ?)
    """, (chat_id, ticker.upper().strip(), alert_type.lower().strip(), target_value, condition.lower().strip(), timestamp))
    alert_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return alert_id

def get_active_alerts():
    conn = get_db_connection()
    rows = conn.execute("""
    SELECT id, chat_id, ticker, alert_type, target_value, condition 
    FROM user_alerts 
    WHERE triggered = 0
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def mark_alert_triggered(alert_id: int):
    conn = get_db_connection()
    conn.execute("UPDATE user_alerts SET triggered = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()

def list_user_alerts(chat_id: int):
    conn = get_db_connection()
    rows = conn.execute("""
    SELECT id, ticker, alert_type, target_value, condition, triggered, timestamp 
    FROM user_alerts 
    WHERE chat_id = ? 
    ORDER BY id DESC
    """, (chat_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_user_alert(chat_id: int, alert_id: int):
    conn = get_db_connection()
    conn.execute("DELETE FROM user_alerts WHERE chat_id = ? AND id = ?", (chat_id, alert_id))
    conn.commit()
    conn.close()

# User Memories Helper Functions
def add_user_memory(chat_id: int, memory_text: str) -> int:
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO user_memories (chat_id, memory_text, timestamp)
    VALUES (?, ?, ?)
    """, (chat_id, memory_text.strip(), timestamp))
    memory_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return memory_id

def get_user_memories(chat_id: int):
    conn = get_db_connection()
    rows = conn.execute("""
    SELECT id, memory_text, timestamp 
    FROM user_memories 
    WHERE chat_id = ? 
    ORDER BY id DESC
    """, (chat_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_user_memory(chat_id: int, memory_id: int):
    conn = get_db_connection()
    conn.execute("DELETE FROM user_memories WHERE chat_id = ? AND id = ?", (chat_id, memory_id))
    conn.commit()
    conn.close()
