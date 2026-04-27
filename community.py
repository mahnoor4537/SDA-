"""
community.py  UC-13: Community Awards

Awards are computed on-the-fly from the current month's data.
Four categories: Top Rated Movie, Most Active Reviewer,
Most Watched Movie, Genre of the Month.

SQLite changes vs MSSQL original:
  - YEAR(col) / MONTH(col)  →  strftime('%Y', col) / strftime('%m', col)
  - SELECT TOP 1 … → SELECT … LIMIT 1
  - GETDATE() → datetime('now')
  - HAVING COUNT(*) >= 1 preserved (works in SQLite)
"""

from flask import Blueprint, jsonify, session
from db import get_connection

community_bp = Blueprint("community", __name__)


def _login_required():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please log in first."}), 401
    return None


# ── UC-13: Award computation ───────────────────────────────────────────────────

def _compute_awards(cursor, year: int, month: int) -> dict:
    """
    Compute four award categories for the given year/month.
    SQLite: strftime('%Y', col) and strftime('%m', col) replace YEAR()/MONTH().
    """
    month_str = f"{year:04d}-{month:02d}"

    # ── 1. Top Rated Movie of the Month ───────────────────────────────────────
    cursor.execute(
        """
        SELECT m.Title, AVG(r.RatingValue) AS Avg, COUNT(*) AS Cnt
        FROM   Ratings r
        JOIN   VW_MoviesComplete m ON r.MovieID = m.MovieID
        WHERE  strftime('%Y-%m', r.RatedAt) = ?
        AND    m.IsApproved = 1
        GROUP  BY m.MovieID, m.Title
        HAVING COUNT(*) >= 1
        ORDER  BY AVG(r.RatingValue) DESC, COUNT(*) DESC
        LIMIT  1
        """,
        (month_str,)
    )
    row = cursor.fetchone()
    top_movie = {
        "title": row[0] if row else None,
        "value": f"{float(row[1]):.1f}★ ({row[2]} ratings)" if row else None,
    }

    # ── 2. Most Active Reviewer ────────────────────────────────────────────────
    cursor.execute(
        """
        SELECT u.Username, COUNT(*) AS ReviewCount
        FROM   Reviews rv
        JOIN   Users   u ON rv.UserID = u.UserID
        WHERE  strftime('%Y-%m', rv.CreatedAt) = ?
        GROUP  BY u.UserID, u.Username
        ORDER  BY COUNT(*) DESC
        LIMIT  1
        """,
        (month_str,)
    )
    row = cursor.fetchone()
    top_reviewer = {
        "username": row[0] if row else None,
        "value":    f"{row[1]} review{'s' if row and row[1] != 1 else ''}" if row else None,
    }

    # ── 3. Most Watched (Watchlist Adds) ──────────────────────────────────────
    cursor.execute(
        """
        SELECT m.Title, COUNT(*) AS Adds
        FROM   Watchlist w
        JOIN   VW_MoviesComplete m ON w.MovieID = m.MovieID
        WHERE  strftime('%Y-%m', w.AddedAt) = ?
        AND    m.IsApproved = 1
        GROUP  BY m.MovieID, m.Title
        ORDER  BY COUNT(*) DESC
        LIMIT  1
        """,
        (month_str,)
    )
    row = cursor.fetchone()
    most_watched = {
        "title": row[0] if row else None,
        "value": f"{row[1]} watchlist add{'s' if row and row[1] != 1 else ''}" if row else None,
    }

    # ── 4. Genre of the Month ─────────────────────────────────────────────────
    cursor.execute(
        """
        SELECT m.Genres, COUNT(*) AS Cnt
        FROM   Ratings r
        JOIN   VW_MoviesComplete m ON r.MovieID = m.MovieID
        WHERE  strftime('%Y-%m', r.RatedAt) = ?
        AND    m.Genres IS NOT NULL
        GROUP  BY m.Genres
        ORDER  BY COUNT(*) DESC
        """,
        (month_str,)
    )
    genre_counts = {}
    for genres_str, cnt in cursor.fetchall():
        for g in genres_str.split(","):
            g = g.strip()
            if g:
                genre_counts[g] = genre_counts.get(g, 0) + cnt

    top_genre_name  = max(genre_counts, key=genre_counts.get) if genre_counts else None
    top_genre_count = genre_counts.get(top_genre_name, 0) if top_genre_name else 0

    top_genre = {
        "genre": top_genre_name,
        "value": f"{top_genre_count} rating{'s' if top_genre_count != 1 else ''}" if top_genre_name else None,
    }

    return {
        "top_movie":    top_movie,
        "top_reviewer": top_reviewer,
        "most_watched": most_watched,
        "top_genre":    top_genre,
    }


@community_bp.route("/awards", methods=["GET"])
def get_awards():
    """
    UC-13 Typical Flow: load current month's awards + last 5 months archive.
    UC-13 Alternate Flow (no current month data): returns empty winners + a note.
    """
    err = _login_required()
    if err:
        return err

    try:
        conn   = get_connection()
        cursor = conn.cursor()

        # SQLite: strftime to get current year/month from 'now'
        cursor.execute(
            "SELECT CAST(strftime('%Y', 'now') AS INTEGER), CAST(strftime('%m', 'now') AS INTEGER)"
        )
        row           = cursor.fetchone()
        current_year  = row[0]
        current_month = row[1]

        current_awards = _compute_awards(cursor, current_year, current_month)

        # Check if current month has any activity
        month_str = f"{current_year:04d}-{current_month:02d}"
        cursor.execute(
            "SELECT COUNT(*) FROM Ratings WHERE strftime('%Y-%m', RatedAt) = ?",
            (month_str,)
        )
        has_current_data = cursor.fetchone()[0] > 0

        # Archive: last 5 completed months
        archive = []
        y, m = current_year, current_month
        for _ in range(5):
            m -= 1
            if m == 0:
                m = 12
                y -= 1
            awards = _compute_awards(cursor, y, m)
            if any(v.get("title") or v.get("username") or v.get("genre")
                   for v in awards.values()):
                archive.append({
                    "year":   y,
                    "month":  m,
                    "label":  _month_label(y, m),
                    "awards": awards,
                })

        conn.close()

        return jsonify({
            "success":          True,
            "current_month":    _month_label(current_year, current_month),
            "has_current_data": has_current_data,
            "current_awards":   current_awards,
            "archive":          archive,
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500


def _month_label(year: int, month: int) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[month-1]} {year}"
