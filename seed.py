"""
seed.py — Auto-seed CineMatch database with movies from TMDB + JustWatch.
Called from app.py on startup when the Movies table is empty.
"""

import os
import time
import sqlite3
import requests

try:
    from simplejustwatchapi.justwatch import search as jw_search
    JUSTWATCH_AVAILABLE = True
except ImportError:
    JUSTWATCH_AVAILABLE = False
    print("[seed] simplejustwatchapi not installed — skipping platform data")

TMDB_BASE_URL   = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_PAGES      = 5

GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi",
    53: "Thriller", 10752: "War", 37: "Western"
}

PLATFORM_INFO = {
    "Netflix":            ("Netflix",     "https://netflix.com"),
    "Max":                ("Max",         "https://max.com"),
    "HBO Max":            ("HBO Max",     "https://hbomax.com"),
    "Disney Plus":        ("Disney+",     "https://disneyplus.com"),
    "Amazon Prime Video": ("Prime Video", "https://primevideo.com"),
    "Hulu":               ("Hulu",        "https://hulu.com"),
    "Apple TV Plus":      ("Apple TV+",   "https://tv.apple.com"),
    "Paramount Plus":     ("Paramount+",  "https://paramountplus.com"),
    "Peacock":            ("Peacock",     "https://peacocktv.com"),
}

PLATFORMS_WE_CARE_ABOUT = set(PLATFORM_INFO.keys())


def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_popular_movie_ids(tmdb_key, pages):
    print(f"[seed] Fetching {pages} pages of popular movies from TMDB...")
    ids = []
    for page in range(1, pages + 1):
        try:
            r = requests.get(
                f"{TMDB_BASE_URL}/movie/popular",
                params={"api_key": tmdb_key, "page": page},
                timeout=10
            )
            r.raise_for_status()
            for m in r.json().get("results", []):
                if m["id"] not in ids:
                    ids.append(m["id"])
            print(f"  page {page}/{pages} — {len(ids)} unique IDs so far")
        except Exception as e:
            print(f"  [TMDB] page {page} failed: {e}")
        time.sleep(0.1)
    return ids


def get_movie_details(tmdb_key, tmdb_id):
    try:
        r = requests.get(
            f"{TMDB_BASE_URL}/movie/{tmdb_id}",
            params={"api_key": tmdb_key, "append_to_response": "credits,videos"},
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [TMDB] details fetch failed for {tmdb_id}: {e}")
        return None


def insert_movie(conn, details):
    cursor = conn.cursor()
    tmdb_id = details.get("id")

    cursor.execute("SELECT MovieID FROM Movies WHERE TMDB_ID = ?", (tmdb_id,))
    if cursor.fetchone():
        return None

    title        = details.get("title", "Unknown")
    release_date = details.get("release_date", "")
    release_year = int(release_date[:4]) if len(release_date) >= 4 else None
    runtime      = details.get("runtime") or None
    description  = details.get("overview", "") or None

    poster_path  = details.get("poster_path")
    poster_url   = f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else None

    backdrop_path = details.get("backdrop_path")
    backdrop_url  = f"{TMDB_IMAGE_BASE}{backdrop_path}" if backdrop_path else None

    trailer_url = None
    for video in details.get("videos", {}).get("results", []):
        if video.get("type") == "Trailer" and video.get("site") == "YouTube":
            trailer_url = f"https://www.youtube.com/watch?v={video['key']}"
            break

    director = None
    for person in details.get("credits", {}).get("crew", []):
        if person.get("job") == "Director":
            director = person.get("name")
            break

    cast_list = [a.get("name") for a in details.get("credits", {}).get("cast", [])[:5]]
    cast_str  = ", ".join(cast_list) if cast_list else None

    try:
        cursor.execute(
            """
            INSERT INTO Movies
                (TMDB_ID, Title, ReleaseYear, Runtime, Description,
                 PosterURL, BackdropURL, TrailerURL, Director, "Cast", AddedBy, IsApproved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
            """,
            (tmdb_id, title, release_year, runtime, description,
             poster_url, backdrop_url, trailer_url, director, cast_str)
        )
        movie_id = cursor.lastrowid

        genre_ids = [g["id"] for g in details.get("genres", [])] or details.get("genre_ids", [])

        for gid in genre_ids:
            genre_name = GENRE_MAP.get(gid)
            if not genre_name:
                continue
            cursor.execute("SELECT GenreID FROM Genres WHERE GenreName = ?", (genre_name,))
            row = cursor.fetchone()
            if row:
                db_genre_id = row["GenreID"]
            else:
                cursor.execute("INSERT INTO Genres (GenreName) VALUES (?)", (genre_name,))
                db_genre_id = cursor.lastrowid
            try:
                cursor.execute(
                    "INSERT INTO MovieGenres (MovieID, GenreID) VALUES (?, ?)",
                    (movie_id, db_genre_id)
                )
            except sqlite3.IntegrityError:
                pass

        conn.commit()
        return movie_id

    except Exception as e:
        conn.rollback()
        print(f"  [seed] insert failed for '{title}': {e}")
        return None


def get_or_create_platform(conn, jw_name):
    display_name, website = PLATFORM_INFO.get(jw_name, (jw_name, ""))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT PlatformID FROM StreamingPlatforms WHERE PlatformName = ?",
        (display_name,)
    )
    row = cursor.fetchone()
    if row:
        return row["PlatformID"]
    cursor.execute(
        "INSERT INTO StreamingPlatforms (PlatformName, Website) VALUES (?, ?)",
        (display_name, website)
    )
    conn.commit()
    return cursor.lastrowid


def link_platform(conn, movie_id, platform_id):
    try:
        conn.execute(
            "INSERT INTO MoviePlatforms (MovieID, PlatformID, AvailableFrom) VALUES (?, ?, datetime('now'))",
            (movie_id, platform_id)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass


def get_jw_platforms(title, year):
    if not JUSTWATCH_AVAILABLE:
        return []
    try:
        results = jw_search(title, "US", "en", count=5, best_only=False)
        if not results:
            return []

        best = None
        title_lower = title.lower()
        for entry in results:
            if entry.object_type != "MOVIE":
                continue
            if entry.title.lower() == title_lower:
                if year and hasattr(entry, "release_year") and entry.release_year:
                    if entry.release_year == year:
                        best = entry
                        break
                else:
                    best = entry
                    break

        if not best:
            for entry in results:
                if entry.object_type == "MOVIE":
                    best = entry
                    break

        if not best:
            return []

        platforms = set()
        for offer in best.offers:
            if offer.monetization_type == "FLATRATE":
                name = offer.package.name
                if name in PLATFORMS_WE_CARE_ABOUT:
                    platforms.add(name)

        return list(platforms)

    except Exception as e:
        print(f"  [JustWatch] error for '{title}': {e}")
        return []


def run():
    # Read config fresh at call time so env vars are always available
    tmdb_key = os.getenv("TMDB_API_KEY", "")
    db_path  = os.getenv("SQLITE_DB_PATH", "cinematch.db")

    if not tmdb_key:
        print("[seed] TMDB_API_KEY not set — skipping seed")
        return

    print(f"[seed] Starting seed — DB: {db_path}")

    tmdb_ids = fetch_popular_movie_ids(tmdb_key, TMDB_PAGES)
    print(f"[seed] {len(tmdb_ids)} movies to process")

    inserted_movies = []
    skipped = 0
    conn = get_connection(db_path)

    for i, tmdb_id in enumerate(tmdb_ids, 1):
        details = get_movie_details(tmdb_key, tmdb_id)
        if not details:
            skipped += 1
            continue

        title        = details.get("title", "?")
        release_date = details.get("release_date", "")
        release_year = int(release_date[:4]) if len(release_date) >= 4 else None

        movie_id = insert_movie(conn, details)
        if movie_id:
            print(f"  [{i}/{len(tmdb_ids)}] ✅ {title} ({release_year})")
            inserted_movies.append((movie_id, title, release_year))
        else:
            skipped += 1

        time.sleep(0.15)

    conn.close()
    print(f"[seed] TMDB done — inserted {len(inserted_movies)}, skipped {skipped}")

    if not JUSTWATCH_AVAILABLE or not inserted_movies:
        print("[seed] Skipping JustWatch pass")
        return

    print(f"[seed] Starting JustWatch pass for {len(inserted_movies)} movies...")
    linked = 0
    conn = get_connection(db_path)

    for i, (movie_id, title, release_year) in enumerate(inserted_movies, 1):
        platforms = get_jw_platforms(title, release_year)
        if platforms:
            for jw_name in platforms:
                platform_id = get_or_create_platform(conn, jw_name)
                link_platform(conn, movie_id, platform_id)
            linked += 1
            print(f"  [{i}/{len(inserted_movies)}] {title} → {', '.join(platforms)}")
        time.sleep(0.8)

    conn.close()
    print(f"[seed] JustWatch done — {linked} movies linked to platforms")
    print("[seed] Seeding complete ✅")


if __name__ == "__main__":
    run()
