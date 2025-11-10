from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime
import os
import threading
import sys

app = Flask(__name__)
CORS(app)

# Read TMDB API key from environment variable
TMDB_API_KEY = os.getenv('TMDB_API_KEY', 'YOUR TMDB API KEY')
TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Global movie cache
all_movies_cache = []

def fetch_and_cache_movies():
    global all_movies_cache
    print("[CACHE] Fetching Malayalam OTT movies...", flush=True)
    sys.stdout.flush()

    today = datetime.now().strftime("%Y-%m-%d")
    final_movies = []

    for page in range(1, 301):
        print(f"[INFO] Checking page {page}", flush=True)
        sys.stdout.flush()
        
        params = {
            "api_key": TMDB_API_KEY,
            "with_original_language": "ml",
            "sort_by": "release_date.desc",
            "release_date.lte": today,
            "region": "IN",
            "page": page
        }

        try:
            print(f"[DEBUG] Making request for page {page}...", flush=True)
            sys.stdout.flush()
            
            response = requests.get(f"{TMDB_BASE_URL}/discover/movie", params=params, timeout=15)
            
            print(f"[DEBUG] Response status: {response.status_code}", flush=True)
            sys.stdout.flush()
            
            results = response.json().get("results", [])
            
            print(f"[DEBUG] Page {page} got {len(results)} results", flush=True)
            sys.stdout.flush()
            
            if not results:
                print(f"[DEBUG] No results on page {page}, breaking", flush=True)
                sys.stdout.flush()
                break

            for movie in results:
                movie_id = movie.get("id")
                title = movie.get("title")
                if not movie_id or not title:
                    continue

                # Check OTT availability in India
                try:
                    providers_url = f"{TMDB_BASE_URL}/movie/{movie_id}/watch/providers"
                    prov_response = requests.get(providers_url, params={"api_key": TMDB_API_KEY}, timeout=10)
                    prov_data = prov_response.json()

                    # Check if movie has providers in India
                    if "results" not in prov_data or "IN" not in prov_data["results"]:
                        print(f"[DEBUG] {title} has no providers in India, skipping", flush=True)
                        sys.stdout.flush()
                        continue

                    india_providers = prov_data["results"]["IN"]
                    
                    # Check if ANY type of provider exists (flatrate, buy, rent)
                    has_provider = "flatrate" in india_providers or "buy" in india_providers or "rent" in india_providers
                    
                    if not has_provider:
                        print(f"[DEBUG] {title} has no OTT providers in India, skipping", flush=True)
                        sys.stdout.flush()
                        continue

                    # Get IMDb ID
                    try:
                        ext_url = f"{TMDB_BASE_URL}/movie/{movie_id}/external_ids"
                        ext_response = requests.get(ext_url, params={"api_key": TMDB_API_KEY}, timeout=10)
                        ext_data = ext_response.json()
                        imdb_id = ext_data.get("imdb_id")

                        if imdb_id and imdb_id.startswith("tt"):
                            movie["imdb_id"] = imdb_id
                            final_movies.append(movie)
                            print(f"[DEBUG] Added: {title} ({imdb_id}) - Providers: {list(india_providers.keys())}", flush=True)
                            sys.stdout.flush()
                    except Exception as e:
                        print(f"[DEBUG] Could not get IMDb ID for {title}: {e}", flush=True)
                        sys.stdout.flush()

                except Exception as e:
                    print(f"[DEBUG] Error checking providers for movie {movie_id}: {e}", flush=True)
                    sys.stdout.flush()
                    continue

        except requests.Timeout:
            print(f"[ERROR] Page {page} TIMEOUT", flush=True)
            sys.stdout.flush()
            break
        except Exception as e:
            print(f"[ERROR] Page {page} failed: {str(e)}", flush=True)
            sys.stdout.flush()
            break

    # Deduplicate
    seen_ids = set()
    unique_movies = []
    for movie in final_movies:
        imdb_id = movie.get("imdb_id")
        if imdb_id and imdb_id not in seen_ids:
            seen_ids.add(imdb_id)
            unique_movies.append(movie)

    all_movies_cache = unique_movies
    print(f"[CACHE] Fetched {len(all_movies_cache)} Malayalam OTT movies ✅", flush=True)
    sys.stdout.flush()


def to_stremio_meta(movie):
    try:
        imdb_id = movie.get("imdb_id")
        title = movie.get("title")
        if not imdb_id or not title:
            return None

        return {
            "id": imdb_id,
            "type": "movie",
            "name": title,
            "poster": f"https://image.tmdb.org/t/p/w500{movie['poster_path']}" if movie.get("poster_path") else None,
            "description": movie.get("overview", ""),
            "releaseInfo": movie.get("release_date", ""),
            "background": f"https://image.tmdb.org/t/p/w780{movie['backdrop_path']}" if movie.get("backdrop_path") else None
        }
    except Exception as e:
        print(f"[ERROR] to_stremio_meta failed: {e}")
        return None


@app.route("/manifest.json")
def manifest():
    return jsonify({
        "id": "org.malayalam.catalog",
        "version": "1.0.0",
        "name": "Malayalam",
        "description": "Latest Malayalam Movies on OTT",
        "resources": ["catalog"],
        "types": ["movie"],
        "catalogs": [{
            "type": "movie",
            "id": "malayalam",
            "name": "Malayalam"
        }],
        "idPrefixes": ["tt"]
    })


@app.route("/catalog/movie/malayalam.json")
def catalog():
    print("[INFO] Catalog requested")

    try:
        metas = [meta for meta in (to_stremio_meta(m) for m in all_movies_cache) if meta]
        print(f"[INFO] Returning {len(metas)} total movies ✅")
        return jsonify({"metas": metas})
    except Exception as e:
        print(f"[ERROR] Catalog error: {e}")
        return jsonify({"metas": []})


@app.route("/refresh")
def refresh():
    def do_refresh():
        try:
            fetch_and_cache_movies()
            print("[REFRESH] Background refresh complete ✅")
        except Exception as e:
            import traceback
            print(f"[REFRESH ERROR] {traceback.format_exc()}")

    threading.Thread(target=do_refresh, daemon=True).start()
    return jsonify({"status": "refresh started in background"})


# Start cache fetch in background thread
threading.Thread(target=fetch_and_cache_movies, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000)
