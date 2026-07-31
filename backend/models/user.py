from datetime import datetime, timezone
from models.database import get_db


def save_user(phone, socketio, name=""):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT phone FROM users WHERE phone=?", (phone,))
        is_new = cursor.fetchone() is None

        # Explicit UTC with a 'Z' suffix — see models/message.py for why.
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cursor.execute(
            "INSERT OR IGNORE INTO users (phone, name, first_seen, last_seen) VALUES (?, ?, ?, ?)",
            (phone, name, now, now),
        )
        if name:
            cursor.execute(
                "UPDATE users SET last_seen=?, name=? WHERE phone=?",
                (now, name, phone),
            )
        else:
            cursor.execute(
                "UPDATE users SET last_seen=? WHERE phone=?",
                (now, phone),
            )
        conn.commit()

        if is_new:
            socketio.emit("new_user", {
                "phone": phone,
                "name": name,
                "human_mode": 0,
                "total_messages": 0,
                "last": "New user",
            })
            print(f"New user: {name or phone} ({phone})")

        return is_new

    except Exception as e:
        print(f"save_user error: {e}")
        return False
    finally:
        conn.close()


def get_user_mode(phone) -> int:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT human_mode FROM users WHERE phone=?", (phone,))
        row = cursor.fetchone()
        return row["human_mode"] if row else 0
    except Exception as e:
        print(f"get_user_mode error: {e}")
        return 0
    finally:
        conn.close()


def toggle_user_mode(phone, socketio):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT human_mode FROM users WHERE phone=?", (phone,))
        row = cursor.fetchone()
        if not row:
            return None
        new_mode = 0 if row["human_mode"] == 1 else 1
        cursor.execute("UPDATE users SET human_mode=? WHERE phone=?", (new_mode, phone))
        conn.commit()
        socketio.emit("mode_changed", {"phone": phone, "human_mode": new_mode})
        print(f"User {phone} -> {'HUMAN' if new_mode else 'AI'} mode")
        return new_mode
    except Exception as e:
        print(f"toggle_user_mode error: {e}")
        return None
    finally:
        conn.close()


def update_user_meta(phone, tags, notes, socketio):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET tags=?, notes=? WHERE phone=?",
            (tags, notes, phone),
        )
        conn.commit()
        socketio.emit("user_updated", {"phone": phone, "tags": tags, "notes": notes})
    except Exception as e:
        print(f"update_user_meta error: {e}")
    finally:
        conn.close()


def get_all_users():
    conn = get_db()
    cursor = conn.cursor()
    try:
        # unread_count is computed from the messages table itself (how
        # many incoming customer messages have an id greater than the
        # last one this user's chat was marked read up to) rather than
        # kept as a separately-incremented counter — that way it's
        # always consistent with the actual message log, and correctly
        # reflects messages that arrived while the dashboard was closed
        # (which an in-memory-only counter in the frontend can't see).
        cursor.execute("""
            SELECT u.phone, u.name, u.human_mode, u.tags, u.notes,
                   u.total_messages, u.first_seen, u.last_seen, u.last_message,
                   (SELECT COUNT(*) FROM messages m
                    WHERE m.phone = u.phone
                      AND m.direction = 'user'
                      AND m.id > u.last_read_message_id) AS unread_count
            FROM users u
            ORDER BY u.last_seen DESC
        """)
        rows = cursor.fetchall()
        return [
            {
                "phone": r["phone"],
                "name": r["name"] or "",
                "human_mode": r["human_mode"],
                "tags": r["tags"] or "",
                "notes": r["notes"] or "",
                "total_messages": r["total_messages"] or 0,
                "first_seen": r["first_seen"] or "",
                "last_seen": r["last_seen"],
                "last": r["last_message"] or "No messages",
                "unread_count": r["unread_count"] or 0,
            }
            for r in rows
        ]
    except Exception as e:
        print(f"get_all_users error: {e}")
        return []
    finally:
        conn.close()


def mark_read(phone, socketio=None):
    """Persist that staff has read everything up to this user's latest
    message. Called when a dashboard opens/selects a chat. Storing this
    in the DB (instead of only in frontend React state) means the
    unread badge survives the dashboard being closed and reopened, and
    stays correct across multiple dashboard instances/tabs.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """UPDATE users
               SET last_read_message_id = COALESCE(
                   (SELECT MAX(id) FROM messages WHERE phone = ?), last_read_message_id
               )
               WHERE phone = ?""",
            (phone, phone),
        )
        conn.commit()
        if socketio:
            # Let any OTHER connected dashboard tab/instance know this
            # chat was read too, so unread badges stay in sync across
            # multiple open dashboards, not just the one that read it.
            socketio.emit("user_update", {"phone": phone, "unread_count": 0})
        return True
    except Exception as e:
        print(f"mark_read error: {e}")
        return False
    finally:
        conn.close()