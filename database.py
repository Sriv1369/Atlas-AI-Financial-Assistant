import sqlite3
import json
import logging
import os
from datetime import datetime
from config import DATABASE_PATH

logger = logging.getLogger(__name__)

# Resolved DB path that can fall back if directory creation fails (e.g. permission issues on Render)
_resolved_db_path = DATABASE_PATH

DATABASE_URL = os.getenv("DATABASE_URL")
IS_POSTGRES = DATABASE_URL is not None and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"))

def get_db_connection():
    if IS_POSTGRES:
        import psycopg2
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url)
        return conn
    else:
        global _resolved_db_path
        db_dir = os.path.dirname(_resolved_db_path)
        if db_dir:
            try:
                os.makedirs(db_dir, exist_ok=True)
            except (PermissionError, OSError) as e:
                logger.warning(f"Directory creation failed for '{db_dir}'. Falling back to local './assistant.db'. Error: {e}")
                _resolved_db_path = "assistant.db"
        conn = sqlite3.connect(_resolved_db_path)
        conn.row_factory = sqlite3.Row
        return conn

def db_execute(conn, sql, params=()):
    if IS_POSTGRES:
        sql = sql.replace('?', '%s')
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return cursor

def row_to_dict(cursor, row):
    if row is None:
        return None
    if not IS_POSTGRES:
        return dict(row)
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}

def rows_to_list(cursor, rows):
    if not rows:
        return []
    if not IS_POSTGRES:
        return [dict(r) for r in rows]
    desc = cursor.description
    return [{col[0]: r[i] for i, col in enumerate(desc)} for r in rows]

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if IS_POSTGRES:
        # Create Users Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id BIGINT PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            timestamp TEXT,
            role TEXT, -- 'user', 'assistant'
            message TEXT,
            FOREIGN KEY(chat_id) REFERENCES users(chat_id)
        )
        """)
        
        # Create Google Credentials Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS google_credentials (
            chat_id BIGINT PRIMARY KEY,
            credentials TEXT, -- JSON string of serialized credentials
            FOREIGN KEY(chat_id) REFERENCES users(chat_id)
        )
        """)
        
        # Create User Documents Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_documents (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
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
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
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
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            memory_text TEXT,
            timestamp TEXT,
            FOREIGN KEY(chat_id) REFERENCES users(chat_id)
        )
        """)
    else:
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
    cursor = db_execute(conn, "SELECT * FROM users WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        user_dict = row_to_dict(cursor, row)
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
        db_execute(conn, """
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
        db_execute(conn, """
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
    db_execute(conn, "UPDATE users SET preferences = ? WHERE chat_id = ?", (json.dumps(prefs), chat_id))
    conn.commit()
    conn.close()

# Chat History Helper Functions
def get_chat_history(chat_id, limit=20):
    conn = get_db_connection()
    cursor = db_execute(conn, """
    SELECT role, message, timestamp 
    FROM conversations 
    WHERE chat_id = ? 
    ORDER BY id DESC LIMIT ?
    """, (chat_id, limit))
    rows = cursor.fetchall()
    conn.close()
    
    # Reverse to restore chronological order
    history = [dict(row) for row in reversed(rows_to_list(cursor, rows))]
    return history

def add_chat_message(chat_id, role, message):
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    db_execute(conn, """
    INSERT INTO conversations (chat_id, timestamp, role, message)
    VALUES (?, ?, ?, ?)
    """, (chat_id, timestamp, role, message))
    conn.commit()
    conn.close()

# Google Credentials Helper Functions
def save_google_credentials(chat_id, creds_dict):
    conn = get_db_connection()
    creds_str = json.dumps(creds_dict)
    if IS_POSTGRES:
        db_execute(conn, """
        INSERT INTO google_credentials (chat_id, credentials)
        VALUES (?, ?)
        ON CONFLICT (chat_id)
        DO UPDATE SET credentials = EXCLUDED.credentials
        """, (chat_id, creds_str))
    else:
        db_execute(conn, """
        INSERT OR REPLACE INTO google_credentials (chat_id, credentials)
        VALUES (?, ?)
        """, (chat_id, creds_str))
    conn.commit()
    conn.close()

def get_google_credentials(chat_id):
    conn = get_db_connection()
    cursor = db_execute(conn, "SELECT credentials FROM google_credentials WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        try:
            r_dict = row_to_dict(cursor, row)
            return json.loads(r_dict['credentials'])
        except Exception:
            return None
    return None

def delete_google_credentials(chat_id):
    conn = get_db_connection()
    db_execute(conn, "DELETE FROM google_credentials WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# User Documents Helper Functions
def save_user_document(chat_id: int, file_name: str, mime_type: str, content: str) -> int:
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    sql = """
    INSERT INTO user_documents (chat_id, file_name, mime_type, content, timestamp)
    VALUES (?, ?, ?, ?, ?)
    """
    params = (chat_id, file_name, mime_type, content, timestamp)
    if IS_POSTGRES:
        sql = sql.replace('?', '%s') + " RETURNING id"
        cursor.execute(sql, params)
        doc_id = cursor.fetchone()[0]
    else:
        cursor.execute(sql, params)
        doc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return doc_id

def list_user_documents(chat_id: int):
    conn = get_db_connection()
    cursor = db_execute(conn, """
    SELECT id, file_name, mime_type, timestamp 
    FROM user_documents 
    WHERE chat_id = ? 
    ORDER BY id DESC
    """, (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows_to_list(cursor, rows)

def get_user_document_content(chat_id: int, doc_id: int):
    conn = get_db_connection()
    cursor = db_execute(conn, """
    SELECT file_name, content 
    FROM user_documents 
    WHERE chat_id = ? AND id = ?
    """, (chat_id, doc_id))
    row = cursor.fetchone()
    conn.close()
    return row_to_dict(cursor, row)

# User Alerts Helper Functions
def create_user_alert(chat_id: int, ticker: str, alert_type: str, target_value: float, condition: str) -> int:
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    sql = """
    INSERT INTO user_alerts (chat_id, ticker, alert_type, target_value, condition, triggered, timestamp)
    VALUES (?, ?, ?, ?, ?, 0, ?)
    """
    params = (chat_id, ticker.upper().strip(), alert_type.lower().strip(), target_value, condition.lower().strip(), timestamp)
    if IS_POSTGRES:
        sql = sql.replace('?', '%s') + " RETURNING id"
        cursor.execute(sql, params)
        alert_id = cursor.fetchone()[0]
    else:
        cursor.execute(sql, params)
        alert_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return alert_id

def get_active_alerts():
    conn = get_db_connection()
    cursor = db_execute(conn, """
    SELECT id, chat_id, ticker, alert_type, target_value, condition 
    FROM user_alerts 
    WHERE triggered = 0
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows_to_list(cursor, rows)

def mark_alert_triggered(alert_id: int):
    conn = get_db_connection()
    db_execute(conn, "UPDATE user_alerts SET triggered = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()

def list_user_alerts(chat_id: int):
    conn = get_db_connection()
    cursor = db_execute(conn, """
    SELECT id, ticker, alert_type, target_value, condition, triggered, timestamp 
    FROM user_alerts 
    WHERE chat_id = ? 
    ORDER BY id DESC
    """, (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows_to_list(cursor, rows)

def delete_user_alert(chat_id: int, alert_id: int):
    conn = get_db_connection()
    db_execute(conn, "DELETE FROM user_alerts WHERE chat_id = ? AND id = ?", (chat_id, alert_id))
    conn.commit()
    conn.close()

# User Memories Helper Functions
def add_user_memory(chat_id: int, memory_text: str) -> int:
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    sql = """
    INSERT INTO user_memories (chat_id, memory_text, timestamp)
    VALUES (?, ?, ?)
    """
    params = (chat_id, memory_text.strip(), timestamp)
    if IS_POSTGRES:
        sql = sql.replace('?', '%s') + " RETURNING id"
        cursor.execute(sql, params)
        memory_id = cursor.fetchone()[0]
    else:
        cursor.execute(sql, params)
        memory_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return memory_id

def get_user_memories(chat_id: int):
    conn = get_db_connection()
    cursor = db_execute(conn, """
    SELECT id, memory_text, timestamp 
    FROM user_memories 
    WHERE chat_id = ? 
    ORDER BY id DESC
    """, (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows_to_list(cursor, rows)

def delete_user_memory(chat_id: int, memory_id: int):
    conn = get_db_connection()
    db_execute(conn, "DELETE FROM user_memories WHERE chat_id = ? AND id = ?", (chat_id, memory_id))
    conn.commit()
    conn.close()
