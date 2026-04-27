"""
UC10 Trending Movies
handles GET /api/trending        = top trending movies (last 7 days)
         GET /api/trending?days= = trending over custom window (max 365 days)

Note: The MSSQL stored procedure SP_GetTrendingMovies has been replaced
with the equivalent inline SQLite query (from db.get_trending_movies).
SQLite does not support stored procedures.
"""

from flask import Blueprint, request, jsonify, session
from db import get_connection

trending_bp = Blueprint("trending", __name__)


def _login_required():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please log in first."}), 401
    return None


# ── UC10 Get trending movies ───────────────────────────────────────────────────

@trending_bp.route("/trending", methods=["GET"])
def get_trending():
    err = _login_required()
    if err:
        return err

    days  = request.args.get("days", 7, type=int)
    top_n = request.args.get("top",  20, type=int)

    days  = max(1, min(days, 365))
    top_n = max(1, min(top_n, 100))

    try:
        conn   = get_connection()
        cursor = conn.cursor()

        # SQLite: datetime('now', '-N days') replaces DATEADD(day, -N, GETDATE())
        # This is equivalent to the MSSQL SP_GetTrendingMovies logic
        days_param = f"-{days} days"
        cursor.execute(
            """
            SELECT  m.MovieID,
                    m.Title,
                    m.ReleaseYear,
                    m.Runtime,
                    m.Description,
                    m.PosterURL,
                    m.TrailerURL,
                    m.Director,
                    m.Cast,
                    m.AverageRating,
                    m.TotalRatings,
                    m.Genres,
                    m.Platforms,
                    COUNT(DISTINCT r.UserID) AS RecentRatings,
                    COUNT(DISTINCT w.UserID) AS RecentWatchlistAdds
            FROM    VW_MoviesComplete m
            LEFT    JOIN Ratings   r ON m.MovieID = r.MovieID
                                     AND r.RatedAt  >= datetime('now', ?)
            LEFT    JOIN Watchlist w ON m.MovieID = w.MovieID
                                     AND w.AddedAt  >= datetime('now', ?)
            WHERE   m.IsApproved = 1
            GROUP   BY m.MovieID, m.Title, m.ReleaseYear, m.Runtime,
                       m.Description, m.PosterURL, m.TrailerURL,
                       m.Director, m.Cast, m.AverageRating,
                       m.TotalRatings, m.Genres, m.Platforms
            HAVING  COUNT(DISTINCT r.UserID) + COUNT(DISTINCT w.UserID) > 0
            ORDER   BY COUNT(DISTINCT r.UserID) + COUNT(DISTINCT w.UserID) DESC
            LIMIT   ?
            """,
            (days_param, days_param, top_n)
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({
                "success": True,
                "days":    days,
                "data":    [],
                "message": f"No trending movies in the last {days} days."
            }), 200

        movies = [
            {
                "movie_id":              row["MovieID"],
                "title":                 row["Title"],
                "release_year":          row["ReleaseYear"],
                "runtime":               row["Runtime"],
                "description":           row["Description"],
                "poster_url":            row["PosterURL"]  or "",
                "trailer_url":           row["TrailerURL"] or "",
                "director":              row["Director"]   or "",
                "cast":                  row["Cast"]       or "",
                "average_rating":        float(row["AverageRating"]) if row["AverageRating"] else 0.0,
                "total_ratings":         row["TotalRatings"] or 0,
                "genres":                row["Genres"]    or "",
                "platforms":             row["Platforms"] or "",
                "recent_ratings":        row["RecentRatings"],
                "recent_watchlist_adds": row["RecentWatchlistAdds"],
                "trend_score":           row["RecentRatings"] + row["RecentWatchlistAdds"],
            }
            for row in rows
        ]

        return jsonify({
            "success": True,
            "days":    days,
            "data":    movies
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Server error: {str(e)}"}), 500
