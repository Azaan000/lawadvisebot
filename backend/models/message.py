from datetime import datetime
from models.database import get_db
from utils.logger import get_logger

log = get_logger(__name__)


def save_message(
    phone,
    message,
    direction,
    socketio,
    status="sent",
    message_type="text",
    media_path=None,
    file_name=None,
    whatsapp_message_id=None,
    source="",
):
    conn = get_db()
    cursor = conn.cursor()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """INSERT INTO messages
               (phone, message, direction, status, timestamp,
                message_type, media_path, file_name, whatsapp_message_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (phone, message, direction, status, now,
             message_type, media_path, file_name, whatsapp_message_id),
        )
        msg_id = cursor.lastrowid

        # Kept in sync here (same row we're already updating for
        # total_messages/last_seen) so get_all_users can read it directly
        # instead of running a per-user correlated subquery against the
        # messages table — matters once this table has real volume.
        if message:
            last_message_preview = message[:100]
        elif message_type != "text":
            last_message_preview = f"[{message_type}]"
        else:
            last_message_preview = ""

        cursor.execute(
            "UPDATE users SET total_messages = total_messages + 1, last_seen=?, last_message=? WHERE phone=?",
            (now, last_message_preview, phone),
        )
        conn.commit()

        cursor.execute("SELECT * FROM users WHERE phone=?", (phone,))
        user = cursor.fetchone()

        socketio.emit("new_message", {
            "phone": phone,
            "message": message or "",
            "direction": direction,
            "status": status,
            "timestamp": now,
            "message_type": message_type or "text",
            "file_name": file_name or "",
            "media_path": media_path or "",
            "msg_id": msg_id,
            "whatsapp_message_id": whatsapp_message_id or "",
            "source": source,
        })

        if user:
            socketio.emit("user_update", {
                "phone": user["phone"],
                "human_mode": user["human_mode"],
                "tags": user["tags"] or "",
                "total_messages": user["total_messages"],
                "last": (message or "Sent a file")[:50],
                "last_seen": user["last_seen"],
            })

        return msg_id
    except Exception as e:
        log.error(f"save_message error: {e}")
        return None
    finally:
        conn.close()


# WhatsApp's status webhooks (sent -> delivered -> read) are NOT
# guaranteed to arrive in order over the network — a delayed "delivered"
# callback can land after the "read" one already did. Without a rank
# check, that later "delivered" blindly overwrites "read" and the
# checkmarks visibly regress in the dashboard even though the customer
# genuinely did read it. This enforces the update only ever moves the
# status forward (except "failed", which can happen at any point and
# should always win since it's the one status staff need to notice).
_STATUS_RANK = {"sending": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 4}


def update_message_status(whatsapp_message_id, status, socketio):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT phone, status FROM messages WHERE whatsapp_message_id=?",
            (whatsapp_message_id,),
        )
        row = cursor.fetchone()
        if not row:
            return

        current_status = row["status"] or "sent"
        current_rank = _STATUS_RANK.get(current_status, 0)
        new_rank = _STATUS_RANK.get(status, 0)

        if new_rank < current_rank and status != "failed":
            log.info(
                f"Ignoring out-of-order '{status}' "
                f"(already '{current_status}') for {whatsapp_message_id}"
            )
            return

        cursor.execute(
            "UPDATE messages SET status=? WHERE whatsapp_message_id=?",
            (status, whatsapp_message_id),
        )
        conn.commit()

        socketio.emit("status_update", {
            "whatsapp_message_id": whatsapp_message_id,
            "status": status,
            "phone": row["phone"],
        })
    except Exception as e:
        log.error(f"update_message_status error: {e}")
    finally:
        conn.close()


def get_messages(phone, search=""):
    conn = get_db()
    cursor = conn.cursor()
    try:
        if search:
            cursor.execute(
                """SELECT message, direction, status, timestamp,
                          message_type, media_path, file_name, whatsapp_message_id
                   FROM messages WHERE phone=? AND message LIKE ?
                   ORDER BY id DESC LIMIT 100""",
                (phone, f"%{search}%"),
            )
        else:
            cursor.execute(
                """SELECT message, direction, status, timestamp,
                          message_type, media_path, file_name, whatsapp_message_id
                   FROM messages WHERE phone=? ORDER BY id DESC LIMIT 100""",
                (phone,),
            )
        rows = cursor.fetchall()
        rows = list(reversed(rows))
        return [
            {
                "message": r["message"] or "",
                "direction": r["direction"],
                "status": r["status"] or "sent",
                "timestamp": r["timestamp"],
                "message_type": r["message_type"] or "text",
                "media_path": r["media_path"] or "",
                "file_name": r["file_name"] or "",
                "whatsapp_message_id": r["whatsapp_message_id"] or "",
            }
            for r in rows
        ]
    except Exception as e:
        log.error(f"get_messages error: {e}")
        return []
    finally:
        conn.close()


def get_all_messages_for_export(phone=None):
    conn = get_db()
    cursor = conn.cursor()
    try:
        if phone:
            cursor.execute(
                "SELECT message, direction, status, timestamp FROM messages WHERE phone=? ORDER BY id ASC",
                (phone,),
            )
        else:
            cursor.execute(
                "SELECT phone, message, direction, status, timestamp FROM messages ORDER BY id ASC"
            )
        return cursor.fetchall()
    except Exception as e:
        log.error(f"get_all_messages_for_export error: {e}")
        return []
    finally:
        conn.close()