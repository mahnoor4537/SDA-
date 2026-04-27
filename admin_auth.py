"""
admin_auth.py — Admin Authentication (separate session namespace from users).

Security note:
  Admin accounts live in the Users table with Role = 'Admin'.
  A regular user session (user_id) never contains admin_id, so a normal user
  cannot reach any admin endpoint regardless of their Role field.
"""

from flask import Blueprint, request, jsonify, session
import bcrypt
from db import get_connection

admin_auth_bp = Blueprint("admin_auth", __name__)


# ── Login ──────────────────────────────────────────────────────────────────────

@admin_auth_bp.route("/admin/login", methods=["POST"])
def admin_login():
    """
    Authenticate against Users WHERE Role = 'Admin'.
    Uses a separate session namespace (admin_id) so a regular user
    session can never grant admin access.
    """
    data       = request.get_json() or {}
    identifier = (data.get("identifier") or "").strip()
    password   = data.get("password") or ""

    if not identifier or not password:
        return jsonify({"success": False,
                        "message": "Username/email and password are required."}), 400

    try:
        conn   = get_connection()
        cursor = conn.cursor()

        # Only rows with Role = 'Admin' qualify — regular users are rejected here
        # SQLite: LOWER() works the same; no MSSQL-specific syntax needed
        cursor.execute(
            """
            SELECT UserID, Username, PasswordHash, IsActive
            FROM   Users
            WHERE  (Username = ? OR LOWER(Email) = LOWER(?))
            AND    Role = 'Admin'
            """,
            (identifier, identifier)
        )
        row = cursor.fetchone()

        if row is None:
            conn.close()
            return jsonify({"success": False, "message": "Invalid credentials."}), 401

        user_id       = row["UserID"]
        username      = row["Username"]
        password_hash = row["PasswordHash"]
        is_active     = row["IsActive"]

        if not is_active:
            conn.close()
            return jsonify({"success": False,
                            "message": "This admin account has been deactivated."}), 403

        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            conn.close()
            return jsonify({"success": False, "message": "Invalid credentials."}), 401

        # SQLite: datetime('now') instead of GETDATE()
        cursor.execute(
            "UPDATE Users SET LastLogin = datetime('now') WHERE UserID = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()

        session["admin_id"]       = user_id
        session["admin_username"] = username

        return jsonify({
            "success":  True,
            "message":  "Login successful.",
            "admin_id": user_id,
            "username": username,
            "redirect": "/admin/dashboard",
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ── Logout ─────────────────────────────────────────────────────────────────────

@admin_auth_bp.route("/admin/logout", methods=["POST"])
def admin_logout():
    """Clear only the admin session keys, leaving any user session intact."""
    session.pop("admin_id",       None)
    session.pop("admin_username", None)
    return jsonify({"success": True, "message": "Logged out."}), 200


# ── Session check ──────────────────────────────────────────────────────────────

@admin_auth_bp.route("/admin/me", methods=["GET"])
def admin_me():
    """Used by admin pages on load to verify the admin session is active."""
    if "admin_id" not in session:
        return jsonify({"logged_in": False}), 200
    return jsonify({
        "logged_in": True,
        "admin_id":  session["admin_id"],
        "username":  session["admin_username"],
    }), 200
