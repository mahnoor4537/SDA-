"""
seed.py — Auto-seed CineMatch database with movies from TMDB + JustWatch.
Called from app.py on startup when the Movies table is empty.

Usage:
    from seed import run
    run()
"""

import os
import sqlite3
import requests
import time

# ── Config (read at call time inside run(), not at import) ────────────────────

TMDB_BASE      = "https://api.themoviedb.org/3"
TMDB_IMG_BASE  = "https://image.tmdb.org/t/p/w500"
# Fetch from multiple TMDB endpoints for a diverse library
# Each endpoint × PAGES_PER_ENDPOINT pages × 20 movies = ~400 movies + genre top picks
PAGES_PER_ENDPOINT = 5
TMDB_ENDPOINTS = [
    "/movie/popular",
    "/movie/top_rated",
]
# Top genres for variety — 2 pages each = 20 movies per genre
# TMDB genre IDs: 28=Action, 35=Comedy, 18=Drama, 27=Horror, 878=Sci-Fi,
#                 53=Thriller, 10749=Romance, 16=Animation, 80=Crime, 99=Documentary
TMDB_GENRE_IDS = [28, 35, 18, 27, 878, 53, 10749, 16, 80, 99]
GENRE_PAGES = 2  # 2 pages per genre


# ── TMDB helpers ──────────────────────────────────────────────────────────────

def tmdb_get(path: str, api_key: str, params: dict = None) -> dict:
    p = {"api_key": api_key}
    if params:
        p.update(params)
    r = requests.get(f"{TMDB_BASE}{path}", params=p, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_movie_detail(tmdb_id: int, api_key: str) -> dict:
    """Fetch full movie detail + credits from TMDB."""
    detail  = tmdb_get(f"/movie/{tmdb_id}", api_key, {"append_to_response": "credits,videos"})
    return detail


def extract_trailer_url(videos: dict) -> str:
    for v in videos.get("results", []):
        if v.get("type") == "Trailer" and v.get("site") == "YouTube":
            return f"https://www.youtube.com/watch?v={v['key']}"
    return ""


def extract_cast(credits: dict, max_actors: int = 5) -> str:
    actors = [m["name"] for m in credits.get("cast", [])[:max_actors]]
    return ", ".join(actors)


def extract_director(credits: dict) -> str:
    for m in credits.get("crew", []):
        if m.get("job") == "Director":
            return m["name"]
    return ""


# ── Streaming platforms via TMDB watch/providers ──────────────────────────────

# Maps TMDB provider_name → the exact name your browse filter checkboxes use
PROVIDER_NAME_MAP = {
    "netflix":                   "Netflix",
    "amazon prime video":        "Prime Video",
    "amazon prime video with ads": "Prime Video",
    "prime video":               "Prime Video",
    "max":                       "HBO Max",
    "hbo max":                   "HBO Max",
    "disney plus":               "Disney+",
    "disney+":                   "Disney+",
    "hulu":                      "Hulu",
    "apple tv plus":             "Apple TV+",
    "apple tv+":                 "Apple TV+",
    "paramount plus":            "Paramount+",
    "paramount+":                "Paramount+",
    "peacock":                   "Peacock",
    "peacock premium":           "Peacock",
}

def get_streaming_platforms(tmdb_id: int, api_key: str) -> list:
    """
    Return list of normalised streaming platform names for a movie
    using TMDB's /watch/providers endpoint (flatrate = subscription streaming).
    """
    try:
        data = tmdb_get(f"/movie/{tmdb_id}/watch/providers", api_key)
        us   = data.get("results", {}).get("US", {})
        # flatrate = subscription (Netflix, Prime, etc.)
        providers = us.get("flatrate", [])
        platforms = []
        seen = set()
        for p in providers:
            raw  = (p.get("provider_name") or "").strip().lower()
            name = PROVIDER_NAME_MAP.get(raw, p.get("provider_name", "").strip())
            if name and name not in seen:
                platforms.append(name)
                seen.add(name)
        return platforms[:5]
    except Exception as e:
        print(f"[seed][providers] error for tmdb_id={tmdb_id}: {e}")
        return []


# ── SQLite insert helpers ─────────────────────────────────────────────────────

def ensure_genre(conn: sqlite3.Connection, genre_name: str) -> int:
    row = conn.execute(
        "SELECT GenreID FROM Genres WHERE GenreName = ?", (genre_name,)
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO Genres (GenreName) VALUES (?)", (genre_name,)
    )
    return cur.lastrowid


def ensure_platform(conn: sqlite3.Connection, platform_name: str) -> int:
    row = conn.execute(
        "SELECT PlatformID FROM StreamingPlatforms WHERE PlatformName = ?",
        (platform_name,)
    ).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO StreamingPlatforms (PlatformName) VALUES (?)", (platform_name,)
    )
    return cur.lastrowid


def insert_movie(conn: sqlite3.Connection, detail: dict) -> int | None:
    """Insert a movie row; return MovieID or None if already exists."""
    tmdb_id = detail.get("id")

    # Skip if already inserted
    existing = conn.execute(
        "SELECT MovieID FROM Movies WHERE TMDB_ID = ?", (tmdb_id,)
    ).fetchone()
    if existing:
        return existing[0]

    title        = detail.get("title") or detail.get("original_title", "")
    original     = detail.get("original_title", "")
    overview     = detail.get("overview", "")
    release_year = None
    release_date = detail.get("release_date", "")
    if release_date and len(release_date) >= 4:
        try:
            release_year = int(release_date[:4])
        except ValueError:
            pass
    runtime     = detail.get("runtime")
    poster_path = detail.get("poster_path", "")
    poster_url  = f"{TMDB_IMG_BASE}{poster_path}" if poster_path else ""
    backdrop    = detail.get("backdrop_path", "")
    backdrop_url = f"https://image.tmdb.org/t/p/w1280{backdrop}" if backdrop else ""

    videos   = detail.get("videos", {})
    credits  = detail.get("credits", {})
    trailer  = extract_trailer_url(videos)
    director = extract_director(credits)
    cast     = extract_cast(credits)
    avg_rating = detail.get("vote_average", 0)
    # Map TMDB 0-10 → 0-5
    avg_rating_scaled = round(float(avg_rating) / 2, 2) if avg_rating else 0.0
    vote_count = detail.get("vote_count", 0)

    cur = conn.execute(
        """
        INSERT INTO Movies
            (TMDB_ID, Title, OriginalTitle, ReleaseYear, Runtime, Description,
             PosterURL, BackdropURL, TrailerURL, Director, "Cast",
             AverageRating, TotalRatings, IsApproved)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            tmdb_id, title, original, release_year, runtime or None,
            overview or None, poster_url or None, backdrop_url or None,
            trailer or None, director or None, cast or None,
            avg_rating_scaled, vote_count,
        )
    )
    return cur.lastrowid


def link_genres(conn: sqlite3.Connection, movie_id: int, tmdb_genres: list):
    for g in tmdb_genres:
        genre_id = ensure_genre(conn, g["name"])
        conn.execute(
            "INSERT OR IGNORE INTO MovieGenres (MovieID, GenreID) VALUES (?, ?)",
            (movie_id, genre_id)
        )


def link_platforms(conn: sqlite3.Connection, movie_id: int, platforms: list):
    for name in platforms:
        platform_id = ensure_platform(conn, name)
        conn.execute(
            "INSERT OR IGNORE INTO MoviePlatforms (MovieID, PlatformID) VALUES (?, ?)",
            (movie_id, platform_id)
        )


# ── Main entry point ──────────────────────────────────────────────────────────

def run():
    global TMDB_API_KEY, DB_PATH
    TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
    DB_PATH      = os.getenv("SQLITE_DB_PATH", "cinematch.db")

    if not TMDB_API_KEY:
        print("[seed] TMDB_API_KEY not set — skipping seed")
        return

    print(f"[seed] Starting seed into {DB_PATH} ...")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")

    inserted = 0
    skipped  = 0

    # Build full list of (endpoint, params) to fetch from
    fetch_jobs = []
    for endpoint in TMDB_ENDPOINTS:
        for page in range(1, PAGES_PER_ENDPOINT + 1):
            fetch_jobs.append((endpoint, {"page": page}))
    for genre_id in TMDB_GENRE_IDS:
        for page in range(1, GENRE_PAGES + 1):
            fetch_jobs.append(("/discover/movie", {
                "page": page,
                "with_genres": genre_id,
                "sort_by": "vote_count.desc",
                "vote_count.gte": 100,
            }))

    total_jobs = len(fetch_jobs)
    print(f"[seed] {total_jobs} fetch jobs planned (~{total_jobs * 20} movies before dedup)")

    try:
        for job_num, (endpoint, params) in enumerate(fetch_jobs, 1):
            print(f"[seed] Job {job_num}/{total_jobs}: {endpoint} page {params.get('page')} ...")
            try:
                data    = tmdb_get(endpoint, TMDB_API_KEY, params)
                results = data.get("results", [])
            except Exception as e:
                print(f"[seed] Fetch failed for {endpoint}: {e}")
                continue

            for movie_stub in results:
                tmdb_id = movie_stub.get("id")
                title   = movie_stub.get("title", "")
                if not tmdb_id:
                    continue

                # Check if already in DB before full detail fetch
                existing = conn.execute(
                    "SELECT MovieID FROM Movies WHERE TMDB_ID = ?", (tmdb_id,)
                ).fetchone()
                if existing:
                    skipped += 1
                    continue

                # Fetch full detail
                try:
                    detail = fetch_movie_detail(tmdb_id, TMDB_API_KEY)
                    time.sleep(0.25)  # be kind to TMDB rate limits
                except Exception as e:
                    print(f"[seed] Detail fetch failed for {tmdb_id} ({title}): {e}")
                    continue

                movie_id = insert_movie(conn, detail)
                if movie_id is None:
                    skipped += 1
                    continue

                # Genres
                link_genres(conn, movie_id, detail.get("genres", []))

                # Streaming platforms via JustWatch
                release_year = None
                rd = detail.get("release_date", "")
                if rd and len(rd) >= 4:
                    try:
                        release_year = int(rd[:4])
                    except ValueError:
                        pass

                platforms = get_streaming_platforms(tmdb_id, TMDB_API_KEY)
                if platforms:
                    link_platforms(conn, movie_id, platforms)

                conn.commit()
                inserted += 1
                print(f"[seed] ✓ {title} ({release_year}) — platforms: {platforms or 'none'}")

    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()

    print(f"[seed] Done. Inserted {inserted} movies, skipped {skipped} duplicates.")


if __name__ == "__main__":
    run()
