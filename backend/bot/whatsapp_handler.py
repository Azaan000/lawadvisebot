import os
import time
import mimetypes
import requests

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WA_BASE = "https://graph.facebook.com/v18.0"
MEDIA_FOLDER = "media_files"

# Shared socketio reference set by app.py after init
_socketio = None

def set_socketio(sio):
    global _socketio
    _socketio = sio


def _headers():
    return {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def _handle_wa_error(status_code, response_text, context=""):
    """Central error handler — emits dashboard warning on 401."""
    if status_code == 401:
        msg = (
            "⚠️ WhatsApp token has expired or is invalid. "
            "Messages cannot be sent. Please update WHATSAPP_TOKEN in your .env and restart the server."
        )
        print(f"[WhatsApp 401] {context}: {response_text}")
        if _socketio:
            _socketio.emit("wa_token_error", {
                "message": msg,
                "context": context,
            })
    elif status_code == 429:
        print(f"[WhatsApp 429] Rate limited. {context}")
    else:
        print(f"[WhatsApp {status_code}] {context}: {response_text}")


def send_text(to: str, message: str):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("WhatsApp credentials missing")
        return False, None
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message},
        }
        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            return True, msg_id
        _handle_wa_error(res.status_code, res.text, f"send_text to {to}")
        return False, None
    except Exception as e:
        print(f"send_text error: {e}")
        return False, None


def send_main_menu(to: str):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False, None
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "header": {"type": "text", "text": "BizAdvise & LawAdvise Consulting"},
                "body": {"text": "Welcome! How can we assist you today? Please select a service:"},
                "footer": {"text": "Our experts are here to help you."},
                "action": {
                    "button": "View Services",
                    "sections": [
                        {
                            "title": "BizAdvise Services",
                            "rows": [
                                {"id": "biz_business", "title": "Business Consultancy",    "description": "Register your business / company"},
                                {"id": "biz_ngo",      "title": "NGO / Charity",           "description": "Start a charity or NGO"},
                                {"id": "biz_tax",      "title": "Taxation Services",        "description": "NTN, income tax, sales tax"},
                                {"id": "biz_accounts", "title": "Accountancy",              "description": "Bookkeeping, audits, reports"},
                                {"id": "biz_legal",    "title": "Corporate Legal",          "description": "Contracts, compliance, opinions"},
                                {"id": "biz_digital",  "title": "Digital Marketing",        "description": "SEO, ads, website, social media"},
                                {"id": "biz_urgent",   "title": "Urgent Help",              "description": "FBR notice, SECP, tax deadline"},
                            ]
                        },
                        {
                            "title": "LawAdvise Services",
                            "rows": [
                                {"id": "online_nikah",   "title": "Online Nikah",           "description": "Online marriage guidance"},
                                {"id": "court_marriage", "title": "Court Marriage",          "description": "Court marriage process"},
                                {"id": "divorce_khula",  "title": "Divorce / Khula",        "description": "Divorce and Khula guidance"},
                                {"id": "child_custody",  "title": "Child Custody",          "description": "Custody and guardianship"},
                                {"id": "legal_docs",     "title": "Legal Documentation",    "description": "Document drafting"},
                                {"id": "contact_us",     "title": "Talk to an Expert",      "description": "Speak with our team directly"},
                            ]
                        }
                    ]
                }
            }
        }
        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            msg_id = res.json().get("messages", [{}])[0].get("id")
            return True, msg_id
        _handle_wa_error(res.status_code, res.text, f"send_main_menu to {to}")
        return False, None
    except Exception as e:
        print(f"send_main_menu error: {e}")
        return False, None


def send_service_menu(to: str, service_id: str):
    menus = {
        "online_nikah":   {"header": "Online Marriage / Nikah",      "body": "What would you like to know?", "buttons": [{"id": "nikah_procedure", "title": "Procedure"}, {"id": "nikah_documents", "title": "Documents"}, {"id": "nikah_consult", "title": "Talk to Lawyer"}]},
        "court_marriage": {"header": "Court Marriage",                "body": "What would you like to know?", "buttons": [{"id": "court_procedure", "title": "Procedure"}, {"id": "court_documents", "title": "Documents"}, {"id": "court_consult", "title": "Book Consultation"}]},
        "divorce_khula":  {"header": "Divorce / Khula",               "body": "What would you like to know?", "buttons": [{"id": "divorce_procedure", "title": "Procedure"}, {"id": "divorce_timeline", "title": "Timeline"}, {"id": "divorce_consult", "title": "Book Consultation"}]},
        "child_custody":  {"header": "Child Custody / Guardianship",  "body": "What would you like to know?", "buttons": [{"id": "custody_procedure", "title": "Procedure"}, {"id": "custody_timeline", "title": "Timeline"}, {"id": "custody_consult", "title": "Talk to Expert"}]},
        "maintenance":    {"header": "Maintenance / Dowery",          "body": "What would you like to know?", "buttons": [{"id": "maintenance_procedure", "title": "Procedure"}, {"id": "maintenance_timeline", "title": "Timeline"}, {"id": "maintenance_consult", "title": "Talk to Expert"}]},
        "property_law":   {"header": "Property Law",                  "body": "What would you like to know?", "buttons": [{"id": "property_procedure", "title": "Procedure"}, {"id": "property_timeline", "title": "Timeline"}, {"id": "property_consult", "title": "Book Consultation"}]},
        "inheritance":    {"header": "Inheritance",                   "body": "What would you like to know?", "buttons": [{"id": "inheritance_procedure", "title": "Procedure"}, {"id": "inheritance_timeline", "title": "Timeline"}, {"id": "inheritance_consult", "title": "Talk to Expert"}]},
        "corporate_law":  {"header": "Corporate Law",                 "body": "What would you like to know?", "buttons": [{"id": "corporate_procedure", "title": "Procedure"}, {"id": "corporate_timeline", "title": "Timeline"}, {"id": "corporate_consult", "title": "Talk to Expert"}]},
        "legal_docs":     {"header": "Legal Documentation",           "body": "What would you like to know?", "buttons": [{"id": "docs_procedure", "title": "Procedure"}, {"id": "docs_timeline", "title": "Timeline"}, {"id": "docs_consult", "title": "Book Consultation"}]},
    }
    menu = menus.get(service_id)
    if not menu:
        return False, None
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {"type": "text", "text": menu["header"]},
                "body": {"text": menu["body"]},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}}
                        for btn in menu["buttons"]
                    ]
                }
            }
        }
        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=10,
        )
        if res.status_code == 200:
            return True, res.json().get("messages", [{}])[0].get("id")
        _handle_wa_error(res.status_code, res.text, f"send_service_menu to {to}")
        return False, None
    except Exception as e:
        print(f"send_service_menu error: {e}")
        return False, None


def send_media(to: str, file_path: str, media_type: str, caption: str = ""):
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        return False, None
    media_id = _upload_media(file_path, media_type)
    if not media_id:
        return False, None
    try:
        media_payload = {"id": media_id}
        if caption:
            media_payload["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": media_type,
            media_type: media_payload,
        }
        res = requests.post(
            f"{WA_BASE}/{PHONE_NUMBER_ID}/messages",
            headers=_headers(), json=payload, timeout=30,
        )
        if res.status_code == 200:
            return True, res.json().get("messages", [{}])[0].get("id")
        _handle_wa_error(res.status_code, res.text, f"send_media to {to}")
        return False, None
    except Exception as e:
        print(f"send_media error: {e}")
        return False, None


def _upload_media(file_path: str, media_type: str):
    try:
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = {
                "image": "image/jpeg",
                "audio": "audio/mpeg",
                "video": "video/mp4",
            }.get(media_type, "application/octet-stream")
        with open(file_path, "rb") as f:
            res = requests.post(
                f"{WA_BASE}/{PHONE_NUMBER_ID}/media",
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                files={"file": (os.path.basename(file_path), f, mime_type)},
                data={"messaging_product": "whatsapp", "type": media_type},
            )
        if res.status_code == 200:
            return res.json().get("id")
        _handle_wa_error(res.status_code, res.text, "_upload_media")
        return None
    except Exception as e:
        print(f"_upload_media error: {e}")
        return None


def resolve_media_type(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in {"jpg", "jpeg", "png", "gif", "webp"}:
        return "image"
    if ext in {"mp3", "wav", "ogg"}:
        return "audio"
    if ext in {"mp4", "mov", "avi"}:
        return "video"
    return "document"


def cleanup_old_media(days: int = 30):
    """Delete media files older than `days` days. Call on a schedule."""
    if not os.path.exists(MEDIA_FOLDER):
        return
    cutoff = time.time() - (days * 86400)
    deleted = 0
    freed = 0
    for filename in os.listdir(MEDIA_FOLDER):
        filepath = os.path.join(MEDIA_FOLDER, filename)
        try:
            if os.path.isfile(filepath) and os.path.getmtime(filepath) < cutoff:
                size = os.path.getsize(filepath)
                os.remove(filepath)
                deleted += 1
                freed += size
        except Exception as e:
            print(f"cleanup error for {filepath}: {e}")
    if deleted:
        print(f"[Media cleanup] Deleted {deleted} files, freed {freed / 1024 / 1024:.1f} MB")
    return deleted, freed