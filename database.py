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

        # Create Transactions Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            message_id TEXT,
            date TEXT,
            amount REAL,
            currency TEXT DEFAULT 'INR',
            transaction_type TEXT, -- 'DEBIT' or 'CREDIT'
            merchant TEXT,
            category TEXT,
            account_ref TEXT,
            raw_snippet TEXT,
            created_at TEXT,
            FOREIGN KEY(chat_id) REFERENCES users(chat_id),
            UNIQUE(chat_id, message_id)
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(chat_id, date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(chat_id, category)")
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

        # Create Transactions Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id TEXT,
            date TEXT,
            amount REAL,
            currency TEXT DEFAULT 'INR',
            transaction_type TEXT, -- 'DEBIT' or 'CREDIT'
            merchant TEXT,
            category TEXT,
            account_ref TEXT,
            raw_snippet TEXT,
            created_at TEXT,
            FOREIGN KEY(chat_id) REFERENCES users(chat_id),
            UNIQUE(chat_id, message_id)
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(chat_id, date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(chat_id, category)")
        
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

# --- Transactions & Expense Tracker Helper Functions ---

def save_transaction(
    chat_id: int,
    message_id: str,
    date: str,
    amount: float,
    currency: str = 'INR',
    transaction_type: str = 'DEBIT',
    merchant: str = None,
    category: str = 'Other',
    account_ref: str = None,
    raw_snippet: str = None
) -> bool:
    """
    Save a parsed transaction to database with deduplication on (chat_id, message_id).
    Returns True if a new transaction was inserted, False if it was already present.
    """
    conn = get_db_connection()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    
    if IS_POSTGRES:
        sql = """
        INSERT INTO transactions (
            chat_id, message_id, date, amount, currency, transaction_type,
            merchant, category, account_ref, raw_snippet, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id, message_id) DO NOTHING
        """
        cursor.execute(sql, (
            chat_id, message_id, date, amount, currency, transaction_type,
            merchant, category, account_ref, raw_snippet, timestamp
        ))
        inserted = cursor.rowcount > 0
    else:
        sql = """
        INSERT OR IGNORE INTO transactions (
            chat_id, message_id, date, amount, currency, transaction_type,
            merchant, category, account_ref, raw_snippet, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor.execute(sql, (
            chat_id, message_id, date, amount, currency, transaction_type,
            merchant, category, account_ref, raw_snippet, timestamp
        ))
        inserted = cursor.rowcount > 0
        
    conn.commit()
    conn.close()
    return inserted

def get_existing_transaction_message_ids(chat_id: int) -> set:
    """
    Get a set of all Gmail message_ids already stored for this user to enable O(1) deduplication.
    """
    conn = get_db_connection()
    cursor = db_execute(conn, "SELECT message_id FROM transactions WHERE chat_id = ?", (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    if IS_POSTGRES:
        return {r[0] for r in rows}
    return {r['message_id'] for r in rows}

def get_transactions(
    chat_id: int,
    start_date: str = None,
    end_date: str = None,
    transaction_type: str = None,
    category: str = None,
    limit: int = 50
) -> list:
    """
    Query transactions with optional date range, type, category filtering.
    """
    conn = get_db_connection()
    query = "SELECT * FROM transactions WHERE chat_id = ?"
    params = [chat_id]
    
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if transaction_type:
        query += " AND UPPER(transaction_type) = ?"
        params.append(transaction_type.upper().strip())
    if category:
        query += " AND LOWER(category) = ?"
        params.append(category.lower().strip())
        
    query += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)
    
    cursor = db_execute(conn, query, tuple(params))
    rows = cursor.fetchall()
    conn.close()
    return rows_to_list(cursor, rows)

def get_monthly_expense_summary(chat_id: int, year: int, month: int) -> dict:
    """
    Compute aggregate monthly statistics: total debited, total credited, net savings, transaction counts.
    """
    conn = get_db_connection()
    month_prefix = f"{year:04d}-{month:02d}%"
    
    cursor = db_execute(conn, """
    SELECT 
        COALESCE(SUM(CASE WHEN transaction_type = 'DEBIT' THEN amount ELSE 0 END), 0) as total_debited,
        COALESCE(SUM(CASE WHEN transaction_type = 'CREDIT' THEN amount ELSE 0 END), 0) as total_credited,
        COUNT(CASE WHEN transaction_type = 'DEBIT' THEN 1 END) as count_debited,
        COUNT(CASE WHEN transaction_type = 'CREDIT' THEN 1 END) as count_credited
    FROM transactions 
    WHERE chat_id = ? AND date LIKE ?
    """, (chat_id, month_prefix))
    
    row = cursor.fetchone()
    conn.close()
    
    summary = row_to_dict(cursor, row) if row else {
        'total_debited': 0.0,
        'total_credited': 0.0,
        'count_debited': 0,
        'count_credited': 0
    }
    
    total_debited = float(summary.get('total_debited') or 0.0)
    total_credited = float(summary.get('total_credited') or 0.0)
    net_savings = total_credited - total_debited
    savings_rate = (net_savings / total_credited * 100) if total_credited > 0 else 0.0
    
    return {
        'year': year,
        'month': month,
        'total_debited': total_debited,
        'total_credited': total_credited,
        'net_savings': net_savings,
        'savings_rate': round(savings_rate, 1),
        'count_debited': int(summary.get('count_debited') or 0),
        'count_credited': int(summary.get('count_credited') or 0),
        'total_transactions': int(summary.get('count_debited') or 0) + int(summary.get('count_credited') or 0)
    }

def get_category_breakdown(chat_id: int, year: int, month: int) -> list:
    """
    Returns breakdown of expenses by category with totals and percentages.
    """
    conn = get_db_connection()
    month_prefix = f"{year:04d}-{month:02d}%"
    
    cursor = db_execute(conn, """
    SELECT 
        category,
        COALESCE(SUM(amount), 0) as total_amount,
        COUNT(*) as count
    FROM transactions 
    WHERE chat_id = ? AND date LIKE ? AND transaction_type = 'DEBIT'
    GROUP BY category
    ORDER BY total_amount DESC
    """, (chat_id, month_prefix))
    
    rows = cursor.fetchall()
    conn.close()
    categories = rows_to_list(cursor, rows)
    
    total_spend = sum(float(c['total_amount']) for c in categories)
    for c in categories:
        amt = float(c['total_amount'])
        c['total_amount'] = amt
        c['percentage'] = round((amt / total_spend * 100), 1) if total_spend > 0 else 0.0
        
    return categories

def get_top_merchants(chat_id: int, year: int, month: int, limit: int = 5) -> list:
    """
    Returns top spending merchants for a given month.
    """
    conn = get_db_connection()
    month_prefix = f"{year:04d}-{month:02d}%"
    
    cursor = db_execute(conn, """
    SELECT 
        merchant,
        COALESCE(SUM(amount), 0) as total_amount,
        COUNT(*) as count
    FROM transactions 
    WHERE chat_id = ? AND date LIKE ? AND transaction_type = 'DEBIT'
      AND merchant IS NOT NULL AND TRIM(merchant) != ''
    GROUP BY merchant
    ORDER BY total_amount DESC
    LIMIT ?
    """, (chat_id, month_prefix, limit))
    
    rows = cursor.fetchall()
    conn.close()
    merchants = rows_to_list(cursor, rows)
    for m in merchants:
        m['total_amount'] = float(m['total_amount'])
    return merchants

def delete_user_transactions(chat_id: int) -> int:
    """
    Delete all stored transactions for a user.
    """
    conn = get_db_connection()
    cursor = db_execute(conn, "DELETE FROM transactions WHERE chat_id = ?", (chat_id,))
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

