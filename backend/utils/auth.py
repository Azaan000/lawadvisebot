import os
import hmac
from functools import wraps
from flask import request, jsonify

DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET")


def _matches(candidate: str) -> bool:
    """Constant-time comparison — plain `==` short-circuits on the first
    mismatched character, which leaks (very slightly) how many leading
    characters were correct via response timing. hmac.compare_digest
    takes the same time regardless of where the mismatch is."""
    if not candidate:
        return False
    return hmac.compare_digest(candidate, DASHBOARD_SECRET)


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_SECRET:
            print("WARNING: DASHBOARD_SECRET not set. All routes are unprotected.")
            return f(*args, **kwargs)
        token = request.headers.get("X-Dashboard-Token")
        query_token = request.args.get("token")
        if _matches(token) or _matches(query_token):
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return decorated