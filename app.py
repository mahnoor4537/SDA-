"""
app.py — CineMatch Flask entry point.
"""

from flask import Flask, send_from_directory
from flask_cors import CORS
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def init_db():
    import sqlite3
    db_path  = os.getenv("SQLITE_DB_PATH", "cinematch.db")
    sql_path = os.path.join(BASE_DIR, "schema_sqlite.sql")
    with open(sql_path, "r") as f:
        sql = f.read()
    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    conn.close()


def seed_if_empty():
    """Seed movies from TMDB + JustWatch if the Movies table is empty."""
    import sqlite3
    db_path = os.getenv("SQLITE_DB_PATH", "cinematch.db")
    conn    = sqlite3.connect(db_path)
    count   = conn.execute("SELECT COUNT(*) FROM Movies").fetchone()[0]
    conn.close()
    if count == 0:
        print("[app] Movies table is empty — starting seed...")
        from seed import run
        run()
    else:
        print(f"[app] Movies table has {count} rows — skipping seed")


init_db()
seed_if_empty()

from auth            import auth_bp
from movies          import movies_bp
from ratings         import ratings_bp
from reviews         import reviews_bp
from watchlist       import watchlist_bp
from trending        import trending_bp
from profile         import profile_bp
from admin           import admin_bp
from admin_auth      import admin_auth_bp
from recommendations import recommendations_bp
from community       import community_bp
from cineblend       import cineblend_bp

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_secret_key")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_NAME"]     = "cinematch_session"

CORS(app, supports_credentials=True, origins=["https://cinematch-x523.onrender.com"])

app.register_blueprint(auth_bp,            url_prefix="/api")
app.register_blueprint(movies_bp,          url_prefix="/api")
app.register_blueprint(ratings_bp,         url_prefix="/api")
app.register_blueprint(reviews_bp,         url_prefix="/api")
app.register_blueprint(watchlist_bp,       url_prefix="/api")
app.register_blueprint(trending_bp,        url_prefix="/api")
app.register_blueprint(profile_bp,         url_prefix="/api")
app.register_blueprint(admin_bp,           url_prefix="/api")
app.register_blueprint(admin_auth_bp,      url_prefix="/api")
app.register_blueprint(recommendations_bp, url_prefix="/api")
app.register_blueprint(community_bp,       url_prefix="/api")
app.register_blueprint(cineblend_bp,       url_prefix="/api")


@app.route("/")
@app.route("/login")
def login_page():
    return send_from_directory(BASE_DIR, "cinematch-login.html")


@app.route("/browse")
def browse_page():
    return send_from_directory(BASE_DIR, "cinematch-browse.html")


@app.route("/profile")
def profile_page():
    return send_from_directory(BASE_DIR, "cinematch-profile.html")


@app.route("/dashboard")
def dashboard_page():
    return send_from_directory(BASE_DIR, "cinematch-dashboard.html")


@app.route("/trending")
def trending_page():
    return send_from_directory(BASE_DIR, "cinematch-trending.html")


@app.route("/watchlist")
def watchlist_page():
    return send_from_directory(BASE_DIR, "cinematch-watchlist.html")


@app.route("/awards")
def awards_page():
    return send_from_directory(BASE_DIR, "cinematch-awards.html")


@app.route("/recommendations")
def recommendations_page():
    return send_from_directory(BASE_DIR, "cinematch-recommendations.html")


@app.route("/cineblend")
def cineblend_page():
    return send_from_directory(BASE_DIR, "cinematch-cineblend.html")


@app.route("/admin/login")
def admin_login_page():
    return send_from_directory(BASE_DIR, "cinematch-admin-login.html")


@app.route("/admin/dashboard")
def admin_dashboard_page():
    return send_from_directory(BASE_DIR, "cinematch-admin.html")


@app.route("/setup-db")
def setup_db():
    init_db()
    return "Database initialized successfully!"

@app.route("/run-seed")
def run_seed():
    try:
        from seed import run
        run()
        import sqlite3
        db_path = os.getenv("SQLITE_DB_PATH", "cinematch.db")
        conn    = sqlite3.connect(db_path)
        count   = conn.execute("SELECT COUNT(*) FROM Movies").fetchone()[0]
        conn.close()
        return f"Seeding complete! Movies in DB: {count}"
    except Exception as e:
        import traceback
        return f"Seed error: {str(e)}\n\n{traceback.format_exc()}", 500


@app.route("/create-admin")
def create_admin():
    import sqlite3, bcrypt
    db_path = os.getenv("SQLITE_DB_PATH", "cinematch.db")
    password = "Admin1234"
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO Users (Username, Email, PasswordHash, FullName, Role, IsActive)
               VALUES ('admin', 'admin@cinematch.com', ?, 'Admin', 'Admin', 1)""",
            (password_hash,)
        )
        conn.commit()
        row = conn.execute("SELECT UserID, Username, Role, IsActive FROM Users WHERE Username = 'admin'").fetchone()
        return f"Admin created! ID={row[0]} Username={row[1]} Role={row[2]} IsActive={row[3]} — Login with admin / Admin1234"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        conn.close()


@app.route("/check-admin")
def check_admin():
    import sqlite3
    db_path = os.getenv("SQLITE_DB_PATH", "cinematch.db")
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT UserID, Username, Email, Role, IsActive, PasswordHash FROM Users WHERE Role = 'Admin'").fetchall()
        if not rows:
            return "No admin users found in DB."
        return "<br>".join([f"ID={r[0]} Username={r[1]} Email={r[2]} Role={r[3]} IsActive={r[4]} HashLen={len(r[5])}" for r in rows])
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        conn.close()


if __name__ == "__main__":
    print("CineMatch backend running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000)
