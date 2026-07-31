import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "database.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # -----------------------------
    # Users table
    # -----------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            first_seen TEXT,
            last_seen TEXT,
            human_mode INTEGER DEFAULT 0,
            tags TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            total_messages INTEGER DEFAULT 0,
            last_message TEXT DEFAULT '',
            last_read_message_id INTEGER DEFAULT 0
        )
    """)

    # -----------------------------
    # Messages table
    # -----------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            message TEXT,
            direction TEXT,
            status TEXT DEFAULT 'sent',
            timestamp TEXT,
            message_type TEXT DEFAULT 'text',
            media_path TEXT,
            file_name TEXT,
            whatsapp_message_id TEXT
        )
    """)

    # -----------------------------
    # Migrations
    # -----------------------------
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT ''")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"Migration warning: {e}")

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_message TEXT DEFAULT ''")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"Migration warning: {e}")

    # Track whether this column is being added for the very first time —
    # the one-time backfill below must only run in that case. If it ran
    # on every startup instead (matching on last_read_message_id == 0),
    # it would keep resetting genuinely-unread conversations to "read"
    # every time the server restarts, which is the exact bug this
    # migration exists to fix, just from the other direction.
    just_added_last_read_column = False
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN last_read_message_id INTEGER DEFAULT 0")
        just_added_last_read_column = True
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            print(f"Migration warning: {e}")

    # -----------------------------
    # Backfill last_message
    # -----------------------------
    cursor.execute("""
        UPDATE users
        SET last_message = (
            SELECT message
            FROM messages m
            WHERE m.phone = users.phone
            ORDER BY m.id DESC
            LIMIT 1
        )
        WHERE (last_message IS NULL OR last_message = '')
    """)

    # -----------------------------
    # Backfill last_read_message_id (one-time only, see comment above)
    # -----------------------------
    if just_added_last_read_column:
        cursor.execute("""
            UPDATE users
            SET last_read_message_id = COALESCE(
                (SELECT MAX(m.id) FROM messages m WHERE m.phone = users.phone), 0
            )
        """)

    # -----------------------------
    # Indexes
    # -----------------------------
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_phone
        ON messages(phone)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_phone_dir
        ON messages(phone, direction, id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_wa_id
        ON messages(whatsapp_message_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_last_seen
        ON users(last_seen DESC)
    """)

    conn.commit()
    conn.close()

    print("Database ready")