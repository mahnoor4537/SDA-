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
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"]   = True

CORS(app, supports_credentials=True)

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
    import requests, os
    key = os.getenv("TMDB_API_KEY", "NOT SET")
    try:
        r = requests.get(
            "https://api.themoviedb.org/3/movie/popular",
            params={"api_key": key, "page": 1},
            timeout=10
        )
        return f"TMDB key: {key[:8]}... | Status: {r.status_code} | Movies found: {len(r.json().get('results', []))}"
    except Exception as e:
        return f"TMDB key: {key[:8]}... | ERROR: {str(e)}"


if __name__ == "__main__":
    print("CineMatch backend running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000)
