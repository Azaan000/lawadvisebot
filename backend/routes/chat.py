import os
import csv
import time as _time
import urllib.parse
from datetime import datetime
from io import StringIO, BytesIO

from flask import Blueprint, request, jsonify, send_file, current_app
from werkzeug.utils import secure_filename

from models.user import get_all_users, toggle_user_mode, update_user_meta
from models.message import save_message, get_messages, get_all_messages_for_export
from models.database import get_db
from bot.whatsapp_handler import send_text, send_media, resolve_media_type
from utils.auth import require_auth

_START_TIME = _time.time()

chat_bp = Blueprint("chat", __name__)

MEDIA_FOLDER = "media_files"
os.makedirs(MEDIA_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "pdf", "doc", "docx", "txt",
    "mp3", "wav", "ogg",
    "mp4", "mov",
}


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _socketio():
    return current_app.extensions["socketio"]


# ── Users ──────────────────────────────────────────────────────────────────

@chat_bp.route("/users", methods=["GET"])
@require_auth
def users():
    return jsonify(get_all_users())


@chat_bp.route("/toggle/<phone>", methods=["POST"])
@require_auth
def toggle(phone):
    new_mode = toggle_user_mode(phone, _socketio())
    if new_mode is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"human_mode": new_mode})


@chat_bp.route("/update-user", methods=["POST"])
@require_auth
def update_user():
    data = request.json
    phone = data.get("phone")
    tags = data.get("tags", "")
    notes = data.get("notes", "")
    if not phone:
        return jsonify({"error": "phone required"}), 400
    update_user_meta(phone, tags, notes, _socketio())
    return jsonify({"success": True})


@chat_bp.route("/delete-user/<phone>", methods=["DELETE"])
@require_auth
def delete_user(phone):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT phone FROM users WHERE phone=?", (phone,))
        if not cursor.fetchone():
            return jsonify({"error": "User not found"}), 404
        cursor.execute("DELETE FROM messages WHERE phone=?", (phone,))
        cursor.execute("DELETE FROM users WHERE phone=?", (phone,))
        conn.commit()
        _socketio().emit("user_deleted", {"phone": phone})
        print(f"Deleted user: {phone}")
        return jsonify({"success": True, "phone": phone})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# ── Messages ───────────────────────────────────────────────────────────────

@chat_bp.route("/messages/<phone>", methods=["GET"])
@require_auth
def messages(phone):
    search = request.args.get("search", "")
    return jsonify(get_messages(phone, search))


@chat_bp.route("/send", methods=["POST"])
@require_auth
def send():
    data = request.json
    phone = data.get("phone")
    message = data.get("message")
    if not phone or not message:
        return jsonify({"error": "phone and message required"}), 400

    success, wa_id = send_text(phone, message)
    status = "sent" if success else "failed"
    save_message(phone, message, "bot", _socketio(),
                 status=status, whatsapp_message_id=wa_id)

    if success:
        return jsonify({"success": True, "message_id": wa_id})
    return jsonify({"success": False, "error": "Failed to send"}), 500


@chat_bp.route("/send-file", methods=["POST"])
@require_auth
def send_file_route():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    phone = request.form.get("phone")
    if not phone:
        return jsonify({"error": "phone required"}), 400

    file = request.files["file"]
    if not file.filename or not _allowed(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    original_name = file.filename
    safe_name = secure_filename(
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{original_name}"
    )
    filepath = os.path.join(MEDIA_FOLDER, safe_name)
    file.save(filepath)

    media_type = resolve_media_type(original_name)
    caption = request.form.get("caption", f"Sent: {original_name}")

    success, wa_id = send_media(phone, filepath, media_type, caption)

    if success:
        # Keep file locally so dashboard can view/download it
        save_message(phone, caption, "bot", _socketio(),
                     message_type=media_type, file_name=original_name,
                     media_path=filepath, whatsapp_message_id=wa_id)
        return jsonify({"success": True, "message_id": wa_id})

    # Only remove on failure
    try:
        os.remove(filepath)
    except Exception:
        pass
    return jsonify({"error": "Failed to send file"}), 500


# ── Media serve ────────────────────────────────────────────────────────────

@chat_bp.route("/media/<path:filename>", methods=["GET"])
@require_auth
def serve_media(filename):
    """Serve media files stored in the media_files folder."""
    decoded = urllib.parse.unquote(filename)
    # Only use the basename — prevent path traversal
    base = os.path.basename(decoded)
    filepath = os.path.join(MEDIA_FOLDER, base)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    return send_file(filepath)


# ── Export ─────────────────────────────────────────────────────────────────

@chat_bp.route("/export/csv", methods=["GET"])
@require_auth
def export_csv():
    phone = request.args.get("phone")
    rows = get_all_messages_for_export(phone)

    output = StringIO()
    writer = csv.writer(output)

    if phone:
        writer.writerow(["Message", "Direction", "Status", "Timestamp"])
        for r in rows:
            writer.writerow([r[0], r[1], r[2], r[3]])
    else:
        writer.writerow(["Phone", "Message", "Direction", "Status", "Timestamp"])
        for r in rows:
            writer.writerow([r[0], r[1], r[2], r[3], r[4]])

    output.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"conversation_{phone or 'all'}_{ts}.csv"

    return send_file(
        BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


# ── Health ─────────────────────────────────────────────────────────────────

@chat_bp.route("/health", methods=["GET"])
def health():
    # Previously this only checked whether env vars were SET, not whether
    # the things they configure actually WORK. A monitoring tool hitting
    # this endpoint would see "status: ok" even with a fully broken
    # database connection. Now it actually attempts a query.
    db_ok = True
    db_error = None
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
    except Exception as e:
        db_ok = False
        db_error = str(e)

    overall_status = "ok" if db_ok else "degraded"

    payload = {
        "status": overall_status,
        "database": "ok" if db_ok else f"error: {db_error}",
        "whatsapp_configured": bool(os.getenv("WHATSAPP_TOKEN")),
        "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "uptime_seconds": round(_time.time() - _START_TIME),
        "timestamp": datetime.now().isoformat(),
    }
    return jsonify(payload), (200 if db_ok else 503)