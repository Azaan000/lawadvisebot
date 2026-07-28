import time
from datetime import datetime
from flask import Blueprint, jsonify
from models.database import get_db
from utils.auth import require_auth

analytics_bp = Blueprint("analytics", __name__)

_analytics_cache = {}
_cache_time = 0
CACHE_TTL = 30

# Keywords that indicate a consultation request
CONSULTATION_KEYWORDS = [
    "consult", "book", "appointment", "talk to", "speak to",
    "contact", "lawyer", "legal expert", "schedule", "call me",
    "reach out", "get in touch", "nikah_consult", "court_consult",
    "divorce_consult", "custody_consult", "maintenance_consult",
    "property_consult", "inheritance_consult", "corporate_consult",
    "docs_consult", "contact_us", "book consultation",
    "talk to a lawyer", "talk to expert", "book a consultation"
]


@analytics_bp.route("/analytics", methods=["GET"])
@require_auth
def get_analytics():
    global _analytics_cache, _cache_time

    if time.time() - _cache_time < CACHE_TTL and _analytics_cache:
        return jsonify(_analytics_cache)

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM messages")
        total_messages = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE human_mode=0")
        ai_users = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE human_mode=1")
        human_users = c.fetchone()[0]

        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT COUNT(*) FROM messages WHERE timestamp LIKE ?", (f"{today}%",))
        messages_today = c.fetchone()[0]

        c.execute("""
            SELECT message_type, COUNT(*) as count
            FROM messages GROUP BY message_type
        """)
        message_types = [{"type": r[0] or "text", "count": r[1]} for r in c.fetchall()]

        c.execute("""
            SELECT phone, total_messages, last_seen
            FROM users ORDER BY total_messages DESC LIMIT 10
        """)
        top_users = [{"phone": r[0], "messages": r[1], "last_seen": r[2]}
                     for r in c.fetchall()]

        c.execute("""
            SELECT AVG(
                (julianday(b.timestamp) - julianday(u.timestamp)) * 24 * 60
            ) AS avg_minutes
            FROM messages u
            JOIN messages b ON b.phone = u.phone
            WHERE u.direction = 'user'
              AND b.direction = 'bot'
              AND b.id > u.id
              AND b.id = (
                  SELECT MIN(id) FROM messages
                  WHERE phone = u.phone AND direction = 'bot' AND id > u.id
              )
        """)
        avg_response = c.fetchone()[0] or 0

        c.execute("""
            SELECT message, COUNT(*) as count
            FROM messages
            WHERE direction='user' AND message_type='text' AND message != ''
            GROUP BY message ORDER BY count DESC LIMIT 10
        """)
        top_questions = [{"question": r[0], "count": r[1]} for r in c.fetchall()]

        c.execute("""
            SELECT DATE(timestamp) as date, COUNT(*) as count
            FROM messages
            WHERE DATE(timestamp) >= DATE('now', '-7 days')
            GROUP BY DATE(timestamp) ORDER BY date
        """)
        daily_activity = [{"date": r[0], "messages": r[1]} for r in c.fetchall()]

        result = {
            "total_users": total_users,
            "total_messages": total_messages,
            "ai_users": ai_users,
            "human_users": human_users,
            "messages_today": messages_today,
            "avg_response_time": round(avg_response, 2),
            "message_types": message_types,
            "top_users": top_users,
            "top_questions": top_questions,
            "daily_activity": daily_activity,
        }

        _analytics_cache = result
        _cache_time = time.time()

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@analytics_bp.route("/consultations", methods=["GET"])
@require_auth
def get_consultations():
    """Return list of users who requested a consultation."""
    conn = get_db()
    c = conn.cursor()
    try:
        # Build SQL LIKE conditions for each keyword
        conditions = " OR ".join(
            ["LOWER(m.message) LIKE ?"] * len(CONSULTATION_KEYWORDS)
        )
        params = [f"%{kw}%" for kw in CONSULTATION_KEYWORDS]

        c.execute(f"""
            SELECT
                u.phone,
                u.name,
                u.last_seen,
                u.tags,
                COUNT(DISTINCT m.id) as consult_count,
                MAX(m.timestamp) as last_request,
                (SELECT message FROM messages
                 WHERE phone = u.phone
                 AND ({conditions})
                 ORDER BY id DESC LIMIT 1) as last_consult_message
            FROM users u
            JOIN messages m ON m.phone = u.phone
            WHERE m.direction = 'user'
            AND ({conditions})
            GROUP BY u.phone
            ORDER BY last_request DESC
        """, params + params)

        rows = c.fetchall()
        return jsonify([
            {
                "phone": r[0],
                "name": r[1] or "",
                "last_seen": r[2],
                "tags": r[3] or "",
                "consult_count": r[4],
                "last_request": r[5],
                "last_consult_message": r[6] or "",
            }
            for r in rows
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@analytics_bp.route("/reload-knowledge", methods=["POST"])
@require_auth
def reload_knowledge():
    from bot.ai_client import reload_knowledge as _reload
    global _cache_time
    knowledge = _reload()
    _cache_time = 0
    return jsonify({"success": True, "length": len(knowledge)})