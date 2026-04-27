"""
UC08 CineBlend — compare logged-in user with a friend by username.
Handle POST /api/cineblend

SQLite changes vs MSSQL original:
  - EXEC SP_CalculateCompatibility  → inline Jaccard similarity query (from db.calculate_compatibility)
  - EXEC SP_GetUserRecommendations  → inline top-genre recommendation query (from db.get_user_recommendations)
  - SELECT TOP N                    → SELECT … LIMIT N
  - CAST(x AS FLOAT)                → CAST(x AS REAL)
  - row.ColumnName                  → row["ColumnName"]  (sqlite3.Row dict access)
  - Multiple fresh cursors no longer needed (SQLite is single-connection friendly)
"""

from flask import Blueprint, request, jsonify, session
from db import get_connection

cineblend_bp = Blueprint("cineblend", __name__)


def _login_required():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please log in first."}), 401
    return None


def _get_top_genres(cursor, user_id: int) -> list:
    """Return top 5 genres the user rated >= 3.5, ordered by average rating."""
    cursor.execute(
        """
        SELECT g.GenreName, AVG(CAST(r.RatingValue AS REAL)) AS AvgRating
        FROM   Ratings r
        JOIN   MovieGenres mg ON r.MovieID = mg.MovieID
        JOIN   Genres g       ON mg.GenreID = g.GenreID
        WHERE  r.UserID = ?
        AND    r.RatingValue >= 3.5
        GROUP  BY g.GenreName
        ORDER  BY AvgRating DESC
        LIMIT  5
        """,
        (user_id,)
    )
    return [row["GenreName"] for row in cursor.fetchall()]


def _get_rating_count(cursor, user_id: int) -> int:
    """Return total number of ratings the user has submitted."""
    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM Ratings WHERE UserID = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    return row["cnt"] if row else 0


def _calculate_compatibility(cursor, user1_id: int, user2_id: int) -> float:
    """
    Jaccard similarity on liked genres (>= 4 stars).
    Replaces MSSQL stored procedure SP_CalculateCompatibility.
    """
    genre_sql = """
        SELECT DISTINCT mg.GenreID
        FROM   Ratings r
        JOIN   MovieGenres mg ON r.MovieID = mg.MovieID
        WHERE  r.UserID = ? AND r.RatingValue >= 4.0
    """
    cursor.execute(genre_sql, (user1_id,))
    u1_genres = {row["GenreID"] for row in cursor.fetchall()}

    cursor.execute(genre_sql, (user2_id,))
    u2_genres = {row["GenreID"] for row in cursor.fetchall()}

    shared = len(u1_genres & u2_genres)
    total  = len(u1_genres | u2_genres)
    return round(shared * 100.0 / total, 2) if total > 0 else 0.0


def _get_recommendations(cursor, user_id: int, top_n: int = 10) -> list:
    """
    Top-N movies from user's top-3 genres not yet rated.
    Replaces MSSQL stored procedure SP_GetUserRecommendations.
    Uses the same CTE logic as db.get_user_recommendations.
    """
    sql = """
    WITH UserTopGenres AS (
        SELECT mg.GenreID
        FROM   Ratings r
        JOIN   MovieGenres mg ON r.MovieID = mg.MovieID
        WHERE  r.UserID = :user_id
          AND  r.RatingValue >= 4.0
        GROUP  BY mg.GenreID
        ORDER  BY AVG(r.RatingValue) DESC, COUNT(*) DESC
        LIMIT  3
    )
    SELECT  m.MovieID,
            m.Title,
            m.ReleaseYear,
            m.Runtime,
            m.PosterURL,
            m.AverageRating,
            m.Genres
    FROM    VW_MoviesComplete m
    JOIN    MovieGenres mg2   ON m.MovieID  = mg2.MovieID
    JOIN    UserTopGenres utg ON mg2.GenreID = utg.GenreID
    WHERE   m.MovieID NOT IN (
                SELECT MovieID FROM Ratings WHERE UserID = :user_id
            )
      AND   m.IsApproved = 1
    GROUP   BY m.MovieID, m.Title, m.ReleaseYear, m.Runtime,
               m.PosterURL, m.AverageRating, m.Genres
    ORDER   BY m.AverageRating DESC
    LIMIT   :top_n
    """
    cursor.execute(sql, {"user_id": user_id, "top_n": top_n})
    return cursor.fetchall()


# ── UC08 Run CineBlend ─────────────────────────────────────────────────────────

@cineblend_bp.route("/cineblend", methods=["POST"])
def run_cineblend():
    err = _login_required()
    if err:
        return err

    data            = request.get_json()
    friend_username = (data or {}).get("friend_username", "").strip()

    if not friend_username:
        return jsonify({"success": False, "message": "Friend username is required."}), 400

    user_id   = session["user_id"]
    friend_id = None

    try:
        conn   = get_connection()
        cursor = conn.cursor()

        # Look up logged-in user
        cursor.execute(
            "SELECT UserID, Username, Email FROM Users WHERE UserID = ?",
            (user_id,)
        )
        me = cursor.fetchone()
        if not me:
            conn.close()
            return jsonify({"success": False, "message": "Your account was not found."}), 404

        # Look up friend by username
        cursor.execute(
            "SELECT UserID, Username, Email FROM Users WHERE Username = ?",
            (friend_username,)
        )
        friend = cursor.fetchone()
        if not friend:
            conn.close()
            return jsonify({"success": False, "message": f"User '{friend_username}' not found."}), 404

        if friend["UserID"] == user_id:
            conn.close()
            return jsonify({"success": False, "message": "You cannot blend with yourself."}), 400

        friend_id = friend["UserID"]

        # Calculate compatibility (inline — replaces SP_CalculateCompatibility)
        compatibility_score = _calculate_compatibility(cursor, user_id, friend_id)

        # Top genres for each user
        my_genres     = _get_top_genres(cursor, user_id)
        friend_genres = _get_top_genres(cursor, friend_id)
        shared_genres = [g for g in my_genres if g in friend_genres]

        # Personalised recommendations (inline — replaces SP_GetUserRecommendations)
        rec_rows = _get_recommendations(cursor, user_id, top_n=10)
        recommendations = [
            {
                "movie_id":       r["MovieID"],
                "title":          r["Title"],
                "release_year":   r["ReleaseYear"],
                "runtime":        r["Runtime"],
                "poster_url":     r["PosterURL"] or "",
                "average_rating": float(r["AverageRating"]) if r["AverageRating"] else 0.0,
                "genres":         r["Genres"] or "",
            }
            for r in rec_rows
        ]

        # Top pick — highest-rated movie in first shared genre
        top_pick = None
        if shared_genres:
            like_genre = shared_genres[0]
            cursor.execute(
                """
                SELECT MovieID, Title, ReleaseYear, Runtime,
                       PosterURL, AverageRating, Genres
                FROM   VW_MoviesComplete
                WHERE  IsApproved = 1
                AND    Genres LIKE ?
                ORDER  BY AverageRating DESC
                LIMIT  1
                """,
                (f"%{like_genre}%",)
            )
            tp = cursor.fetchone()
            if tp:
                top_pick = {
                    "movie_id":       tp["MovieID"],
                    "title":          tp["Title"],
                    "release_year":   tp["ReleaseYear"],
                    "runtime":        tp["Runtime"],
                    "poster_url":     tp["PosterURL"] or "",
                    "average_rating": float(tp["AverageRating"]) if tp["AverageRating"] else 0.0,
                    "genres":         tp["Genres"] or "",
                }

        # Rating counts
        my_count     = _get_rating_count(cursor, user_id)
        friend_count = _get_rating_count(cursor, friend_id)

        conn.close()

        return jsonify({
            "success":             True,
            "compatibility_score": compatibility_score,
            "shared_genres":       shared_genres,
            "my_genres":           my_genres,
            "friend_genres":       friend_genres,
            "me": {
                "username":     me["Username"],
                "rating_count": my_count,
            },
            "friend": {
                "username":     friend["Username"],
                "rating_count": friend_count,
            },
            "top_pick":        top_pick,
            "recommendations": recommendations,
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Server error: {str(e)}\nfriend_id was: {friend_id}"
        }), 500
