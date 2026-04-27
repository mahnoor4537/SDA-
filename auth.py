"""
UC01 logging in / registering — handles login, register, logout
"""

from flask import Blueprint, request, jsonify, session
import bcrypt
import re
from db import get_connection

auth_bp = Blueprint("auth", __name__)


def _is_valid_email(email: str) -> bool:
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$"
    return bool(re.match(pattern, email))


def _is_strong_password(password: str) -> bool:
    """
    Password must be at least 8 characters and contain at least 1
    uppercase letter, 1 lowercase letter, and one digit.
    """
    if len(password) < 8:
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[0-9]", password):
        return False
    return True


# ── Register ───────────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    username         = (data.get("username") or "").strip()
    email            = (data.get("email") or "").strip().lower()
    password         = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not username:
        return jsonify({"success": False, "message": "Username is required."}), 400
    if not email:
        return jsonify({"success": False, "message": "Email is required."}), 400
    if not password:
        return jsonify({"success": False, "message": "Password is required."}), 400

    if len(username) < 3 or len(username) > 50:
        return jsonify({"success": False, "message": "Username must be 3–50 characters."}), 400

    if not _is_valid_email(email):
        return jsonify({"success": False, "message": "Invalid email format."}), 400

    if not _is_strong_password(password):
        return jsonify({
            "success": False,
            "message": "Password must be at least 8 characters and include uppercase, lowercase, and a digit."
        }), 400

    if password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match."}), 400

    try:
        conn   = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM Users WHERE Username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "Username is already taken."}), 409

        cursor.execute("SELECT 1 FROM Users WHERE Email = ?", (email,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"success": False, "message": "An account with this email already exists."}), 409

        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        cursor.execute(
            "INSERT INTO Users (Username, Email, PasswordHash) VALUES (?, ?, ?)",
            (username, email, hashed)
        )
        conn.commit()

        cursor.execute(
            "SELECT UserID, Role FROM Users WHERE Username = ?",
            (username,)
        )
        row     = cursor.fetchone()
        user_id = row["UserID"]
        role    = row["Role"]

        # SQLite: datetime('now') instead of GETDATE()
        cursor.execute(
            "UPDATE Users SET LastLogin = datetime('now') WHERE UserID = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()

        session["user_id"]  = user_id
        session["username"] = username
        session["role"]     = role

        return jsonify({
            "success":  True,
            "message":  "Account created successfully.",
            "user_id":  user_id,
            "username": username,
            "role":     role
        }), 201

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


# ── Login ──────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    identifier = (data.get("identifier") or "").strip()   # username or email
    password   = data.get("password") or ""

    if not identifier:
        return jsonify({"success": False, "message": "Please enter your username or email."}), 400
    if not password:
        return jsonify({"success": False, "message": "Please enter your password."}), 400

    try:
        conn   = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT UserID, Username, PasswordHash, Role, IsActive
            FROM   Users
            WHERE  Username = ? OR Email = ?
            """,
            (identifier, identifier.lower())
        )
        row = cursor.fetchone()

        if row is None:
            conn.close()
            return jsonify({"success": False, "message": "Invalid username/email or password."}), 401

        user_id       = row["UserID"]
        username      = row["Username"]
        password_hash = row["PasswordHash"]
        role          = row["Role"]
        is_active     = row["IsActive"]

        if not is_active:
            conn.close()
            return jsonify({"success": False, "message": "This account has been deactivated."}), 403

        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            conn.close()
            return jsonify({"success": False, "message": "Invalid username/email or password."}), 401

        # SQLite: datetime('now') instead of GETDATE()
        cursor.execute(
            "UPDATE Users SET LastLogin = datetime('now') WHERE UserID = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()

        session["user_id"]  = user_id
        session["username"] = username
        session["role"]     = role

        redirect = "/admin/dashboard" if role == "Admin" else "/browse"

        return jsonify({
            "success":  True,
            "message":  "Login successful.",
            "user_id":  user_id,
            "username": username,
            "role":     role,
            "redirect": redirect
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


# ── Logout ─────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out."}), 200


# ── Session check ──────────────────────────────────────────────────────────────

@auth_bp.route("/me", methods=["GET"])
def me():
    if "user_id" not in session:
        return jsonify({"logged_in": False}), 200
    return jsonify({
        "logged_in": True,
        "user_id":   session["user_id"],
        "username":  session["username"],
        "role":      session["role"]
    }), 200
