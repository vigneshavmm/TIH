from flask import Flask, render_template_string, request, jsonify, send_from_directory
import re
import requests
import math
import os
import time
import json

app = Flask(__name__, static_folder='static', static_url_path='/static')

# ================== CONFIG ================== #
ENABLE_TINYLLAMA = True  # set False if you don't want LLM rephrasing

TINYLLAMA_MODEL_PATH = os.getenv(
    "TINYLLAMA_MODEL_PATH",
    "/Users/appletest/.cache/huggingface/hub/models--TheBloke--TinyLlama-1.1B-Chat-v1.0-GGUF/"
    "snapshots/52e7645ba7c309695bec7ac98f4f005b139cf465/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
)

MAX_REQ_PER_WINDOW = 120   # requests
WINDOW_SEC = 600           # seconds (10 minutes)
RATE_LIMIT = {}            # ip -> [timestamps]

# ================== TinyLlama ================== #
_LLAMA = None  # cached llama_cpp.Llama instance

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()

def get_tinyllama():
    """Lazy-load TinyLlama via llama_cpp."""
    global _LLAMA
    if _LLAMA is not None:
        return _LLAMA

    if not ENABLE_TINYLLAMA:
        return None

    if not os.path.exists(TINYLLAMA_MODEL_PATH):
        print(f"[TINYLLAMA] Model file not found: {TINYLLAMA_MODEL_PATH}")
        return None

    try:
        from llama_cpp import Llama  # type: ignore
    except Exception as e:
        print("[TINYLLAMA] llama_cpp import failed:", repr(e))
        return None

    try:
        print(f"[TINYLLAMA] Loading model from: {TINYLLAMA_MODEL_PATH}")
        _LLAMA = Llama(
            model_path=TINYLLAMA_MODEL_PATH,
            n_ctx=2048,
            n_threads=4,   # adjust to your CPU
            n_gpu_layers=0 # CPU only; set >0 if you have GPU offload
        )
        return _LLAMA
    except Exception as e:
        print("[TINYLLAMA] Failed to load model:", repr(e))
        _LLAMA = None
        return None

def humanize_message(user_query: str, base_message: str) -> str:
    """
    Use TinyLlama to make the base_message sound more natural,
    without changing facts or adding any new content.
    """
    if len(base_message) < 60:
        return base_message

    qn = normalize(user_query)
    if qn in {"hi", "hello", "hey", "hai", "hola", "namaste"}:
        return base_message

    llama = get_tinyllama()
    if llama is None:
        return base_message

    prompt = f"""
You are a map assistant.

Rewrite the reply below so it sounds a bit more natural and conversational,
but do NOT change any facts, numbers, place names, or counts.

Very important rules:
- Do NOT invent or add extra facts or places.
- Do NOT ask the user for more information.
- Do NOT add greetings or signatures.
- Do NOT mention "user query", "assistant reply", or similar meta text.
- Do NOT apologize or explain yourself.
- Keep the structure and bullet points similar.
- Keep it short, clear, and friendly.

Reply ONLY with the rewritten text.

Original reply:
{base_message}

Rewritten:
"""

    try:
        result = llama.create_completion(
            prompt=prompt,
            max_tokens=150,
            temperature=0.12,
            top_p=0.9,
            stop=["Original reply:", "Rewritten:"]
        )

        if not result or "choices" not in result or len(result["choices"]) == 0:
            return base_message

        text = result["choices"][0].get("text", "").strip()

        banned_patterns = [
            r"(?i)user query",
            r"(?i)assistant reply",
            r"(?i)revised text",
            r"(?i)best regards",
            r"(?i)i apologize",
            r"(?i)i am a helpful mapping assistant",
            r"(?i)please provide",
        ]
        for pat in banned_patterns:
            if re.search(pat, text):
                return base_message

        text = text.replace("Rewritten version:", "").strip()

        if not text or len(text.split()) < 3:
            return base_message

        orig_len = len(base_message.split())
        new_len = len(text.split())
        if new_len > orig_len + 10:
            return base_message

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        seen = set()
        cleaned_lines = []
        for line in lines:
            low = line.lower()
            if low not in seen:
                seen.add(low)
                cleaned_lines.append(line)
        text = "\n".join(cleaned_lines).strip()
        return text
    except Exception as e:
        print("[TINYLLAMA] Generation error:", repr(e))
        return base_message

# ================== Rate limiting ================== #
def check_rate_limit(ip: str) -> bool:
    now = time.time()
    timestamps = RATE_LIMIT.get(ip, [])
    timestamps = [t for t in timestamps if now - t < WINDOW_SEC]
    if len(timestamps) >= MAX_REQ_PER_WINDOW:
        RATE_LIMIT[ip] = timestamps
        return False
    timestamps.append(now)
    RATE_LIMIT[ip] = timestamps
    return True

# ================== Geocoding / geometry ================== #
GEOCODE_CACHE = {}
REVERSE_GEOCODE_CACHE = {}

CITY_FALLBACK = {
    "tirupati": (13.6288, 79.4192, "Tirupati, Andhra Pradesh, India"),
    "mumbai": (19.0760, 72.8777, "Mumbai, Maharashtra, India"),
    "delhi": (28.6139, 77.2090, "Delhi, India"),
    "new delhi": (28.6139, 77.2090, "New Delhi, India"),
    "bangalore": (12.9716, 77.5946, "Bangalore, Karnataka, India"),
    "bengaluru": (12.9716, 77.5946, "Bengaluru, Karnataka, India"),
    "chennai": (13.0827, 80.2707, "Chennai, Tamil Nadu, India"),
    "hyderabad": (17.3850, 78.4867, "Hyderabad, Telangana, India"),
    "kolkata": (22.5726, 88.3639, "Kolkata, West Bengal, India"),
    "pune": (18.5204, 73.8567, "Pune, Maharashtra, India"),
    "paris": (48.8566, 2.3522, "Paris, France"),
    "london": (51.5074, -0.1278, "London, United Kingdom"),
    "tokyo": (35.6895, 139.6917, "Tokyo, Japan"),
    "new york": (40.7128, -74.0060, "New York City, USA"),
}

KNOWN_CITIES = [
    (13.6288, 79.4192, "Tirupati"),
    (19.0760, 72.8777, "Mumbai"),
    (28.6139, 77.2090, "Delhi"),
    (12.9716, 77.5946, "Bangalore"),
    (13.0827, 80.2707, "Chennai"),
    (17.3850, 78.4867, "Hyderabad"),
    (22.5726, 88.3639, "Kolkata"),
    (18.5204, 73.8567, "Pune"),
    (48.8566, 2.3522, "Paris"),
    (51.5074, -0.1278, "London"),
    (35.6895, 139.6917, "Tokyo"),
    (40.7128, -74.0060, "New York"),
    (25.2048, 55.2708, "Dubai"),
    (1.3521, 103.8198, "Singapore"),
    (-33.8688, 151.2093, "Sydney"),
    (34.0522, -118.2437, "Los Angeles"),
    (55.7558, 37.6173, "Moscow"),
    (52.5200, 13.4050, "Berlin"),
]

def find_nearest_city(lat, lon):
    best_city = None
    min_dist = float('inf')
    for clat, clon, cname in KNOWN_CITIES:
        dist = haversine_km(lat, lon, clat, clon)
        if dist < min_dist:
            min_dist = dist
            best_city = cname
    return best_city, min_dist

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def geocode_place(text):
    """
    Geocode a place name OR 'lat,lon' string.
    Returns (lat, lon, display_name) or None.
    """
    text = text.strip()

    if "," in text:
        try:
            part1, part2 = [p.strip() for p in text.split(",", 1)]
            lat = float(part1)
            lon = float(part2)
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return None
            return lat, lon, f"({lat:.5f}, {lon:.5f})"
        except Exception:
            pass

    cache_key = text.lower()
    if cache_key in GEOCODE_CACHE:
        lat, lon, name = GEOCODE_CACHE[cache_key]
        print(f"[GEOCODE_CACHE] Hit for {text} -> {name}")
        return lat, lon, name

    if cache_key in CITY_FALLBACK:
        lat, lon, name = CITY_FALLBACK[cache_key]
        print(f"[CITY_FALLBACK] Using cached coords for {text} -> {name}")
        GEOCODE_CACHE[cache_key] = (lat, lon, name)
        return lat, lon, name

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": text, "format": "json", "limit": 1}
    headers = {
        "User-Agent": os.getenv(
            "NOMINATIM_USER_AGENT",
            "MyMapAssistant/1.0 (contact@example.com)"
        )
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        print("Nominatim status:", r.status_code, "for", text)
        if r.status_code == 403:
            print("[NOMINATIM] 403 Forbidden for", text)
            return None
        if r.status_code != 200:
            print("[NOMINATIM] Non-200 status", r.status_code, "for", text)
            return None
        try:
            data = r.json()
        except ValueError as e:
            print("[NOMINATIM] Invalid JSON response:", e)
            return None
        if not data:
            print("Nominatim returned empty list")
            return None
        d = data[0]
        try:
            lat = float(d["lat"])
            lon = float(d["lon"])
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                print(f"[NOMINATIM] Invalid coordinates: lat={lat}, lon={lon}")
                return None
        except (ValueError, KeyError) as e:
            print(f"[NOMINATIM] Error parsing coordinates: {e}")
            return None
        name = d.get("display_name", text)
        GEOCODE_CACHE[cache_key] = (lat, lon, name)
        return lat, lon, name
    except Exception as e:
        print("Geocoding error for", text, ":", e)
        return None

def reverse_geocode(lat, lon):
    key = f"{round(lat, 3)},{round(lon, 3)}"
    if key in REVERSE_GEOCODE_CACHE:
        return REVERSE_GEOCODE_CACHE[key]

    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 10,
    }
    headers = {
        "User-Agent": os.getenv(
            "NOMINATIM_USER_AGENT",
            "MyMapAssistant/1.0 (contact@example.com)"
        )
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=8)
        print("Reverse Nominatim status:", r.status_code, "for", key)
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError as e:
            print("[REVERSE_GEOCODE] Invalid JSON response:", e)
            return None
        name = data.get("display_name")
        if not name:
            return None
        REVERSE_GEOCODE_CACHE[key] = name
        return name
    except Exception as e:
        print("Reverse geocoding error for", key, ":", e)

    city, dist = find_nearest_city(lat, lon)
    if city:
        if dist < 15:
            return f"{city}"
        else:
            return f"{int(dist)}km from {city}"

    return f"({lat:.2f}, {lon:.2f})"

MOVE_KEYWORDS = [
    "fly to",
    "fly me to",
    "go to",
    "take me to",
    "show me",
    "navigate to",
    "center on",
    "center the map on",
    "pan to",
    "move to",
]

def extract_move_place(raw_lower: str):
    for kw in MOVE_KEYWORDS:
        if kw in raw_lower:
            return raw_lower.split(kw, 1)[1].strip(" .,!?:;")
    return None

def looks_like_place_fallback(q: str, qn: str) -> bool:
    words = q.split()
    if len(words) == 0 or len(words) > 4:
        return False
    if len(qn) < 3:
        return False
    control_words = [
        "zoom", "reset", "route", "distance", "measure",
        "marker", "pin", "satellite", "terrain",
        "clear", "help", "3d", "building", "rotate", "spin",
        "analyze", "analyse", "detect", "objects", "here", "around",
        "weather", "forecast", "poi", "restaurants", "restaurant", "atm"
    ]
    if any(w in qn for w in control_words):
        return False
    return any(c.isalpha() for c in q)

# ================== Overpass (OSM Data) ================== #
def overpass_query(q: str):
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    try:
        r = requests.post(OVERPASS_URL, data={"data": q}, timeout=25)
        print("Overpass status:", r.status_code)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as e:
            print("[OVERPASS] Invalid JSON response:", e)
            return None
    except Exception as e:
        print("Overpass error:", e)
        return None

def fetch_lines_bbox(bbox, key):
    south, west, north, east = bbox
    q = f"""
    [out:json][timeout:25];
    (
      way["{key}"]({south},{west},{north},{east});
    );
    out geom;
    """
    data = overpass_query(q)
    if not data:
        return []
    lines = []
    for el in data.get("elements", []):
        if el.get("type") == "way" and "geometry" in el:
            coords = [[p["lat"], p["lon"]] for p in el["geometry"]]
            lines.append(coords)
    return lines

def fetch_centers_bbox(bbox, tag_key, tag_value=None):
    south, west, north, east = bbox
    if tag_value:
        filter_part = f'["{tag_key}"="{tag_value}"]'
    else:
        filter_part = f'["{tag_key}"]'
    q = f"""
    [out:json][timeout:25];
    (
      node{filter_part}({south},{west},{north},{east});
      way{filter_part}({south},{west},{north},{east});
      relation{filter_part}({south},{west},{north},{east});
    );
    out center 100;
    """
    data = overpass_query(q)
    if not data:
        return []
    pts = []
    for el in data.get("elements", []):
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            center = el.get("center")
            if center:
                lat = center.get("lat")
                lon = center.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        name = tags.get("name", tag_key)
        pts.append((lat, lon, name))
    return pts

def fetch_pois_amenity(bbox, amenity_regex):
    south, west, north, east = bbox
    q = f"""
    [out:json][timeout:25];
    (
      node["amenity"~"{amenity_regex}"]({south},{west},{north},{east});
      way["amenity"~"{amenity_regex}"]({south},{west},{north},{east});
      relation["amenity"~"{amenity_regex}"]({south},{west},{north},{east});
    );
    out center 150;
    """
    data = overpass_query(q)
    if not data:
        return []
    pois = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        amenity = tags.get("amenity", "amenity")
        name = tags.get("name", amenity.capitalize())
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            center = el.get("center")
            if center:
                lat = center.get("lat")
                lon = center.get("lon")
        if lat is None or lon is None:
            continue
        pois.append((lat, lon, name, amenity))
    return pois

def detect_objects(lat, lon, radius_deg=0.03):
    south = lat - radius_deg
    north = lat + radius_deg
    west = lon - radius_deg
    east = lon + radius_deg
    bbox = (south, west, north, east)

    railway = fetch_lines_bbox(bbox, "railway")
    roads = fetch_lines_bbox(bbox, "highway")
    buildings = fetch_centers_bbox(bbox, "building")
    waters = fetch_centers_bbox(bbox, "natural", "water") + fetch_centers_bbox(bbox, "waterway")
    greens = (
        fetch_centers_bbox(bbox, "landuse", "forest")
        + fetch_centers_bbox(bbox, "natural", "wood")
        + fetch_centers_bbox(bbox, "leisure", "park")
    )

    summary = {
        "railway_segments": len(railway),
        "road_segments": len(roads),
        "buildings": len(buildings),
        "waters": len(waters),
        "greens": len(greens),
    }

    def lines_to_geojson(lines):
        features = []
        for line in lines:
            coords = [[lng, la] for la, lng in line]
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {}
            })
        return {"type": "FeatureCollection", "features": features}

    def points_to_geojson(points):
        features = []
        for la, lng, name in points:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, la]},
                "properties": {"name": name}
            })
        return {"type": "FeatureCollection", "features": features}

    return {
        "summary": summary,
        "railway_geojson": lines_to_geojson(railway),
        "roads_geojson": lines_to_geojson(roads),
        "buildings_geojson": points_to_geojson(buildings),
        "waters_geojson": points_to_geojson(waters),
        "greens_geojson": points_to_geojson(greens),
    }

def generate_area_analysis(summary):
    buildings = summary.get("buildings", 0)
    roads = summary.get("road_segments", 0)
    greens = summary.get("greens", 0)
    water = summary.get("waters", 0)
    rail = summary.get("railway_segments", 0)

    parts = []

    if buildings > 50:
        parts.append("This is a **high-density urban area** with many buildings.")
    elif buildings > 10:
        parts.append("This appears to be a **suburban or semi-urban area**.")
    else:
        parts.append("This looks like a **rural or sparsely populated area**.")

    if roads > 20:
        parts.append("It has a **dense road network**, indicating high connectivity.")
    elif roads > 5:
        parts.append("There are some roads present.")

    if rail > 0:
        parts.append("A **railway line** passes through this area.")

    if greens > 5:
        parts.append("There is significant **green cover** (parks or vegetation).")
    elif greens > 0:
        parts.append("Some green spaces are visible.")

    if water > 0:
        parts.append("Water bodies (lakes/rivers) are present.")

    return " ".join(parts)

def detect_pois(lat, lon, category: str, radius_deg=0.03):
    south = lat - radius_deg
    north = lat + radius_deg
    west = lon - radius_deg
    east = lon + radius_deg
    bbox = (south, west, north, east)

    if category == "food":
        regex = "restaurant|cafe|fast_food"
        label = "Food & restaurants"
    elif category == "atm":
        regex = "atm|bank"
        label = "ATMs & banks"
    elif category == "fuel":
        regex = "fuel"
        label = "Fuel stations"
    else:
        regex = "restaurant|cafe|fast_food"
        label = "Places"

    pois = fetch_pois_amenity(bbox, regex)
    return label, pois

# ================== Weather (Open-Meteo) ================== #
def get_weather(lat, lon):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current_weather": "true",
    }
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        cw = data.get("current_weather")
        if not cw:
            return None
        code = cw.get("weathercode", 0)
        weather_desc = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            71: "Slight snow",
            73: "Moderate snow",
            75: "Heavy snow",
            80: "Rain showers",
            81: "Rain showers",
            82: "Violent rain showers",
        }.get(code, "Unknown weather")

        return {
            "temperature": cw.get("temperature"),
            "windspeed": cw.get("windspeed"),
            "winddirection": cw.get("winddirection"),
            "weathercode": code,
            "description": weather_desc,
        }
    except Exception as e:
        print("Weather error:", e)
        return None

# ================== Route finding (OSRM) ================== #
def get_route_osrm(start_lat, start_lon, end_lat, end_lon):
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
        "?overview=full&geometries=geojson"
    )
    try:
        r = requests.get(url, timeout=10)
        print("OSRM status:", r.status_code)
        r.raise_for_status()
        try:
            data = r.json()
        except ValueError as e:
            print("[OSRM] Invalid JSON response:", e)
            return None, None, None
        if data.get("code") != "Ok" or not data.get("routes"):
            print("OSRM returned no routes or non-Ok code")
            return None, None, None
        route = data["routes"][0]
        coords = route["geometry"]["coordinates"]
        distance_km = route["distance"] / 1000.0
        duration_min = route["duration"] / 60.0
        return coords, distance_km, duration_min
    except Exception as e:
        print("OSRM error:", e)
        return None, None, None


def parse_route_from_to(q_lower):
    m = re.search(r"route\s+from\s+(.+?)\s+to\s+(.+)", q_lower)
    if not m:
        return None, None
    return m.group(1).strip(" .,!?:;"), m.group(2).strip(" .,!?:;")

# ================== NLP for MapLibre chat ================== #
def process_query(query, center=None, zoom=None):
    q = query.strip()
    q_lower = q.lower()
    qn = normalize(q)

    GREETINGS = {"hi", "hello", "hey", "hai", "hola", "namaste"}
    if qn in GREETINGS:
        return {
            "message": (
                "Hey! 👋 I’m your map assistant.\n\n"
                "You can try things like:\n"
                "- \"Fly to Tirupati\"\n"
                "- \"Show weather here\"\n"
                "- \"Route from Tirupati to Chennai\"\n"
                "- \"Analyze this area\"\n"
                "- \"Distance to Chennai\"\n"
                "- \"Restaurants near here\""
            ),
            "action": None,
        }

    # Basemap switching
    if "satellite" in qn or "imagery" in qn:
        return {
            "message": "Switching to satellite imagery basemap...",
            "action": {"type": "setStyle", "style": "satellite"},
        }

    if "terrain" in qn or "topography" in qn or "relief" in qn:
        return {
            "message": "Switching to terrain / topographic basemap...",
            "action": {"type": "setStyle", "style": "terrain"},
        }

    if any(
        kw in qn
        for kw in ["street map", "default map", "normal map", "osm view", "back to normal"]
    ):
        return {
            "message": "Switching back to standard OpenStreetMap view...",
            "action": {"type": "setStyle", "style": "osm"},
        }

    # Weather
    if "weather" in qn or "forecast" in qn:
        if not center:
            return {
                "message": "To show weather I need the current map center. Move the map and try again.",
                "action": None,
            }
        lat = center.get("lat")
        lon = center.get("lng")
        if lat is None or lon is None:
            return {
                "message": "I couldn't read the map center coordinates for weather.",
                "action": None,
            }
        wx = get_weather(lat, lon)
        if not wx:
            return {
                "message": "I couldn't get weather data for this location.",
                "action": None,
            }

        loc_name = reverse_geocode(lat, lon)
        display_loc = f"**{loc_name}**" if loc_name else "this location"

        msg = (
            f"Weather near {display_loc}:\n"
            f"• Temperature: {wx['temperature']} °C\n"
            f"• Wind: {wx['windspeed']} km/h (dir {wx['winddirection']}°)\n"
            f"• Conditions: {wx['description']}"
        )
        return {"message": msg, "action": None}

    # Routes (from A to B)
    from_place, to_place = parse_route_from_to(q_lower)
    if from_place and to_place:
        start_geo = geocode_place(from_place)
        end_geo = geocode_place(to_place)
        if not start_geo or not end_geo:
            return {
                "message": f"I couldn't geocode one of: '{from_place}' or '{to_place}'.",
                "action": None,
            }
        s_lat, s_lon, s_name = start_geo
        e_lat, e_lon, e_name = end_geo
        coords, dist_km, dur_min = get_route_osrm(s_lat, s_lon, e_lat, e_lon)
        if not coords or len(coords) == 0:
            return {
                "message": f"OSRM couldn't compute a route from {s_name} to {e_name}.",
                "action": None,
            }
        msg = (
            f"Route from {s_name} to {e_name}:\n"
            f"• Distance: {dist_km:.1f} km\n"
            f"• Estimated time: {dur_min:.1f} minutes\n"
            "Showing the route on the map."
        )
        mid_idx = len(coords) // 2
        mid = coords[mid_idx] if mid_idx < len(coords) else coords[0]
        return {
            "message": msg,
            "action": {
                "type": "setRoute",
                "coords": coords,
                "center": mid,
                "zoom": 9,
            },
        }

    # Route from current map center
    if ("route to" in q_lower or "navigate to" in q_lower) and "from" not in q_lower:
        if "route to" in q_lower:
            place_text = q_lower.split("route to", 1)[1].strip(" .,!?:;")
        else:
            place_text = q_lower.split("navigate to", 1)[1].strip(" .,!?:;")

        if not center:
            return {
                "message": "To compute a route I need the current map center as the start.",
                "action": None,
            }
        s_lat = center.get("lat")
        s_lon = center.get("lng")
        dest_geo = geocode_place(place_text)
        if not dest_geo:
            return {
                "message": f"I couldn't find '{place_text}' for routing.",
                "action": None,
            }
        e_lat, e_lon, e_name = dest_geo
        coords, dist_km, dur_min = get_route_osrm(s_lat, s_lon, e_lat, e_lon)
        if not coords or len(coords) == 0:
            return {
                "message": f"OSRM couldn't compute a route to {e_name}.",
                "action": None,
            }
        loc_name = reverse_geocode(s_lat, s_lon) or "current center"
        msg = (
            f"Route from {loc_name} to {e_name}:\n"
            f"• Distance: {dist_km:.1f} km\n"
            f"• Estimated time: {dur_min:.1f} minutes\n"
            "Showing the route on the map."
        )
        mid_idx = len(coords) // 2
        mid = coords[mid_idx] if mid_idx < len(coords) else coords[0]
        return {
            "message": msg,
            "action": {
                "type": "setRoute",
                "coords": coords,
                "center": mid,
                "zoom": 9,
            },
        }

    if "clear route" in qn or "remove route" in qn:
        return {
            "message": "Clearing the route from the map.",
            "action": {"type": "clearRoute"},
        }

    # Distance
    if any(phrase in q_lower for phrase in ["distance to", "how far to", "how far is"]):
        if "distance to" in q_lower:
            place_text = q_lower.split("distance to", 1)[1].strip(" .,!?:;")
        elif "how far to" in q_lower:
            place_text = q_lower.split("how far to", 1)[1].strip(" .,!?:;")
        else:
            place_text = q_lower.split("how far is", 1)[1].strip(" .,!?:;")

        if not place_text:
            return {
                "message": "Please tell me a place, for example: 'Distance to Chennai'.",
                "action": None,
            }

        if not center:
            return {
                "message": "To measure distance I need the current map center. Move the map and try again.",
                "action": None,
            }

        s_lat = center.get("lat")
        s_lon = center.get("lng")
        if s_lat is None or s_lon is None:
            return {
                "message": "I couldn't read the current map center for distance calculation.",
                "action": None,
            }

        dest_geo = geocode_place(place_text)
        if not dest_geo:
            return {
                "message": f"I couldn't find '{place_text}' to measure distance.",
                "action": None,
            }

        d_lat, d_lon, d_name = dest_geo
        d_km = haversine_km(s_lat, s_lon, d_lat, d_lon)

        loc_name = reverse_geocode(s_lat, s_lon) or "current center"
        msg = (
            f"Straight-line distance from {loc_name} to {d_name}:\n"
            f"• ≈ {d_km:.1f} km (great-circle)\n"
            "\nFor a drivable route, you can also ask:\n"
            f"\"Route to {d_name}\" or \"Route from <city> to {d_name}\"."
        )

        return {
            "message": msg,
            "action": {
                "type": "measureDistance",
                "from": [s_lon, s_lat],
                "to": [d_lon, d_lat],
            },
        }

    # Detection
    if any(
        phrase in q_lower
        for phrase in [
            "analyze this area",
            "analyse this area",
            "analyze area",
            "analyse area",
            "detect objects",
            "detect surroundings",
            "what is here",
            "what's here",
            "what is around",
            "what's around",
            "detect buildings",
            "detect trees",
            "detect water bodies",
        ]
    ):
        if not center:
            return {
                "message": "To analyze objects I need the current map center. Move the map and try again.",
                "action": None,
            }
        lat = center.get("lat")
        lon = center.get("lng")
        if lat is None or lon is None:
            return {
                "message": "I couldn't read the map center coordinates.",
                "action": None,
            }

        det = detect_objects(lat, lon)
        s = det["summary"]
        loc_name = reverse_geocode(lat, lon) or "this area"
        msg = (
            f"Object detection (OpenStreetMap) around {loc_name}:\n"
            f"• Railway segments: {s['railway_segments']}\n"
            f"• Road segments: {s['road_segments']}\n"
            f"• Buildings: {s['buildings']}\n"
            f"• Water bodies: {s['waters']}\n"
            f"• Green areas (trees/parks/forests): {s['greens']}\n"
            "\nOverlaying detected objects on the main map. Use the checkboxes to toggle each layer."
        )

        analysis = generate_area_analysis(s)
        msg += f"\n\n**Analysis:**\n{analysis}"

        return {
            "message": msg,
            "action": {
                "type": "setDetections",
                "data": det,
                "center": [lon, lat],
            },
        }

    # POIs
    poi_category = None
    if any(x in qn for x in ["restaurants near", "restaurant near", "food near", "eat near"]):
        poi_category = "food"
    elif any(x in qn for x in ["atms near", "atm near", "cash near", "bank near"]):
        poi_category = "atm"
    elif any(x in qn for x in ["fuel near", "petrol near", "gas station near"]):
        poi_category = "fuel"

    if poi_category:
        if not center:
            return {
                "message": "To find nearby places I need the current map center. Move the map and try again.",
                "action": None,
            }
        lat = center.get("lat")
        lon = center.get("lng")
        if lat is None or lon is None:
            return {
                "message": "I couldn't read the map center for POI search.",
                "action": None,
            }

        label, pois = detect_pois(lat, lon, poi_category)
        loc_name = reverse_geocode(lat, lon) or "this area"

        if not pois:
            return {
                "message": f"I couldn't find any {label.lower()} near {loc_name} in OpenStreetMap.",
                "action": None,
            }

        names = [p[2] for p in pois[:5]]
        msg = (
            f"{label} found near {loc_name}: {len(pois)}\n"
            f"Some examples:\n- " + "\n- ".join(names)
        )
        return {"message": msg, "action": None}

    # Navigation (flyTo)
    place_text = extract_move_place(q_lower)
    if place_text:
        geo = geocode_place(place_text)
        if geo:
            lat, lon, name = geo
            return {
                "message": f"Flying to {name}...",
                "action": {
                    "type": "flyTo",
                    "center": [lon, lat],
                    "zoom": 14,
                    "pitch": 60,
                },
            }
        else:
            return {
                "message": f"I couldn't find '{place_text}' in OpenStreetMap.",
                "action": None,
            }

    if looks_like_place_fallback(q_lower, qn):
        geo = geocode_place(q)
        if geo:
            lat, lon, name = geo
            return {
                "message": f"Flying to {name}...",
                "action": {
                    "type": "flyTo",
                    "center": [lon, lat],
                    "zoom": 15,
                    "pitch": 60,
                },
            }
        else:
            return {
                "message": f"I couldn't find '{q}' in OpenStreetMap.",
                "action": None,
            }

    # Reset
    if "reset" in q_lower:
        return {
            "message": "Resetting the map to the default view.",
            "action": {"type": "reset"},
        }

    # Default help
    return {
        "message": """I can:

🌍 Navigation
- "Fly to Paris"
- "Fly to Tirupati"
- "Go to Tokyo"
- Or just type: "Bangalore" / "New York"

🛰 Basemaps
- "Satellite view"
- "Terrain view"
- "Back to normal map"

☁️ Weather
- "Show weather here"
- "Weather now"

🧭 Routes
- "Route from Tirupati to Chennai"
- "Route to Chennai" (from current map center)
- "Clear route"

📏 Distance
- "Distance to Chennai"
- "How far to Mumbai"

🛰 Detection
- "Analyze this area"
- "Detect buildings and trees"

🍽️ Nearby POIs
- "Restaurants near here"
- "ATMs near here"
- "Fuel near here"
""",
        "action": None,
    }

# ================== HTML templates ================== #
MAIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title> 🌏 GEO AI 🤖</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<link href="https://unpkg.com/maplibre-gl@5.13.0/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl@5.13.0/dist/maplibre-gl.js"></script>
<style>
html, body {
    margin:0; padding:0; height:100%;
    overflow:hidden;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background:#020617; color:#e5e7eb;
}
.container { display:flex; height:100vh; }
#map { flex:1; position:relative; min-height:300px; }
.panel {
    width:360px;
    background:#020617;
    border-left:1px solid #1f2937;
    display:flex; flex-direction:column;
}
.header {
    padding:10px 14px;
    border-bottom:1px solid #1f2937;
}
.chat-logo{
    width: 350px;
    height: 80px;
    object-fit: contain;
    border-radius: 8px;
    background: transparent;
    box-shadow: 0 2px 8px rgba(2,6,23,0.35);
}
.messages {
    flex:1;
    padding:10px;
    overflow-y:auto;
    font-size:13px;
}
.message-row { margin-bottom:8px; }
.message-row.user { text-align:right; }
.message {
    display:inline-block;
    padding:7px 9px;
    border-radius:8px;
    max-width:90%;
    white-space:pre-wrap;
}
.message.assistant {
    background:#111827;
    border:1px solid #1f2937;
}
.message.user {
    background:#2563eb;
}
.input-area {
    padding:8px 10px;
    border-top:1px solid #1f2937;
}
.input-row { display:flex; gap:6px; }
#queryInput {
    flex:1;
    padding:7px 8px;
    border-radius:6px;
    border:1px solid #374151;
    background:#020617;
    color:#e5e7eb;
    font-size:13px;
}
#queryInput::placeholder { color:#6b7280; }
#sendBtn {
    padding:0 12px;
    border-radius:6px;
    border:none;
    background:#2563eb;
    color:white;
    font-size:13px;
    cursor:pointer;
}
#sendBtn:disabled {
    opacity:0.6;
    cursor:default;
}
.status-box {
    position:absolute;
    top:10px; left:10px;
    background:rgba(15,23,42,0.9);
    padding:8px 10px;
    border-radius:8px;
    font-size:11px;
    z-index:5;
}
.quick-btn {
    border:none;
    border-radius:999px;
    padding:3px 6px;
    font-size:11px;
    background:#111827;
    color:#e5e7eb;
    cursor:pointer;
    border:1px solid #1f2937;
}
.quick-btn:hover {
    background:#1f2937;
}

/* Responsive: stack on small screens */
@media (max-width: 900px) {
    .container {
        flex-direction:column;
    }
    .panel {
        width:100%;
        height:45vh;
    }
    #map {
        height:55vh;
    }
}
a { color:#93c5fd; text-decoration:none; }
</style>
</head>
<body>
<div class="container">
    <div id="map">
        <div class="status-box" id="statusBox">
            Center: [78.96, 20.59] | Zoom: 4.2 | Style: osm | Mode: Globe
        </div>
    </div>
    <div class="panel">
        <div class="header">
            <img src="/static/image.jpg" alt="App logo" class="chat-logo" />
            <center><div style="font-size:16px; font-weight:600;">GEO AI Map</div></center>
            <center><div style="font-size:10px; font-weight:600;">Powered by</div></center>
            <center><div style="font-size:12px; font-weight:600;">
                IIT Tirupati Navavishkar I-Hub Foundation (IITTNiF)
            </div></center>
            <center>
                <div style="font-size:11px; color:#9ca3af; margin-top:4px;">
                    <a href="/">Map</a> · <a href="/about">About</a>
                </div>
            </center>
        </div>

        <div id="messages" class="messages"></div>
        <center><div style="font-size:12px; font-weight:600;"> Quick Buttons : </div></center>
        <div style="display:flex; flex-wrap:wrap; gap:2px; margin-bottom:3px;">
            <button class="quick-btn" onclick="runQuick('Fly to Tirupati')">Tirupati</button>
            <button class="quick-btn" onclick="runQuick('Show weather here')">Weather here</button>
            <button class="quick-btn" onclick="runQuick('Route from Tirupati to Chennai')">Tirupati → Chennai</button>
            <button class="quick-btn" onclick="runQuick('Analyze this area')">Analyze area</button>
            <button class="quick-btn" onclick="runQuick('Restaurants near here')">Food near here</button>
        </div>
        <div class="input-area">
            <div class="input-row">
                <input id="queryInput"
                       placeholder='e.g. "Fly to Tirupati" or "Analyze this area"'
                       onkeypress="if(event.key==='Enter'){sendQuery()}" />
                <button id="sendBtn" onclick="sendQuery()">Send</button>
            </div>
            <div style="font-size:12px; color:#9ca3af; margin:4px 0 6px 0;">
                Try: "Fly to Tirupati", "Show weather here", "Route from Tirupati to Chennai",
                "Analyze this area", "Restaurants near here"
            </div>

            <div style="font-size:12px; color:#9ca3af;margin-bottom:2px;">Map layers:</div>
            <label style="font-size:12px; color:#9ca3af;margin-right:3px; display:block; margin-bottom:2px;">
                <input id="chkIndiaBorder" type="checkbox" checked
                       onchange="onIndiaBorderToggle(this.checked)">
                India Border
            </label>

            <div style="font-size:12px; color:#9ca3af;margin-top:6px;">Projection:</div>
            <label style="font-size:12px; color:#9ca3af;margin-right:6px;">
                <input type="radio" name="projMode" value="globe" checked
                       onchange="setProjectionMode('globe')">
                Globe
            </label>
            <label style="font-size:12px; color:#9ca3af;margin-right:6px;">
                <input type="radio" name="projMode" value="mercator"
                       onchange="setProjectionMode('mercator')">
                Flat
            </label>

            <div style="font-size:12px; color:#9ca3af;margin-bottom:2px; margin-top:6px;">
                Detection layers:
            </div>
            <label style="font-size:12px; color:#9ca3af;margin-right:3px;">
                <input id="chkDetRail" type="checkbox" checked
                       onchange="onDetLayerToggle('rail', this.checked)">
                Railways
            </label>
            <label style="font-size:12px; color:#9ca3af;margin-right:3px;">
                <input id="chkDetRoad" type="checkbox" checked
                       onchange="onDetLayerToggle('road', this.checked)">
                Road
            </label>
            <label style="font-size:12px; color:#9ca3af;margin-right:3px;">
                <input id="chkDetBuild" type="checkbox" checked
                       onchange="onDetLayerToggle('building', this.checked)">
                Buildings
            </label>
            <label style="font-size:12px; color:#9ca3af;margin-right:3px;">
                <input id="chkDetWater" type="checkbox" checked
                       onchange="onDetLayerToggle('water', this.checked)">
                Water
            </label>
            <label style="font-size:12px; color:#9ca3af;margin-right:3px;">
                <input id="chkDetGreen" type="checkbox" checked
                       onchange="onDetLayerToggle('green', this.checked)">
                Green
            </label>
        </div>
    </div>
</div>

<script>
// ----- INDIA BORDER DATA PLACEHOLDER (filled by Flask) -----
//__INDIA_BORDER_DATA__

// ---------- Fog / projection config ----------
var FOG_CONFIG = {
    color: "rgb(186,210,235)",
    "high-color": "rgb(36,92,223)",
    "horizon-blend": 0.02,
    "space-color": "rgb(11,11,25)",
    "star-intensity": 0.6
};

var fogEnabled = true;
var currentProjection = 'globe';  // 'globe' or 'mercator';

// ---------- Basemap style objects ----------
var osmStyle = {
    "version": 8,
    "sources": {
        "osm": {
            "type": "raster",
            "tiles": ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"],
            "tileSize": 256,
            "attribution": "© OpenStreetMap contributors"
        }
    },
    "layers": [{
        "id": "osm",
        "type": "raster",
        "source": "osm"
    }]
};

var terrainStyle = {
    "version": 8,
    "sources": {
        "terrain": {
            "type": "raster",
            "tiles": ["https://tile.opentopomap.org/{z}/{x}/{y}.png"],
            "tileSize": 256,
            "attribution": "© OpenTopoMap (CC-BY-SA)",
            "maxzoom": 17
        }
    },
    "layers": [{
        "id": "terrain",
        "type": "raster",
        "source": "terrain"
    }]
};

var satelliteStyle = {
    "version": 8,
    "sources": {
        "sat": {
            "type": "raster",
            "tiles": [
                "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ],
            "tileSize": 256,
            "attribution": "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and others",
            "maxzoom": 19
        }
    },
    "layers": [{
        "id": "sat",
        "type": "raster",
        "source": "sat"
    }]
};

var currentBasemap = "osm";

var MEASURE_SOURCE_ID = 'measure';
var MEASURE_LINE_ID = 'measure-line';

var DET_RAIL_SOURCE = 'det-rail';
var DET_RAIL_LAYER = 'det-rail-line';
var DET_ROAD_SOURCE = 'det-road';
var DET_ROAD_LAYER = 'det-road-line';
var DET_BUILD_SOURCE = 'det-build';
var DET_BUILD_LAYER = 'det-build-circle';
var DET_WATER_SOURCE = 'det-water';
var DET_WATER_LAYER = 'det-water-circle';
var DET_GREEN_SOURCE = 'det-green';
var DET_GREEN_LAYER = 'det-green-circle';

var DET_LAYER_IDS = {
    rail: DET_RAIL_LAYER,
    road: DET_ROAD_LAYER,
    building: DET_BUILD_LAYER,
    water: DET_WATER_LAYER,
    green: DET_GREEN_LAYER
};

// ---------- Map init (India focus) ----------
var map = new maplibregl.Map({
    container: 'map',
    style: osmStyle,
    center: [78.9629, 20.5937],
    zoom: 4.2,
    pitch: 50,
    bearing: 0,
    antialias: true,
    maxPitch: 85,
    renderWorldCopies: false
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

function applyProjection() {
    if (!map || typeof map.setProjection !== 'function') return;
    try {
        if (currentProjection === 'globe') {
            map.setProjection({ type: 'globe' });
            if (typeof map.setFog === 'function') {
                map.setFog(fogEnabled ? FOG_CONFIG : null);
            }
        } else {
            map.setProjection('mercator');
            if (typeof map.setFog === 'function') {
                map.setFog(null);
            }
        }
    } catch (e) {
        console.warn('[PROJECTION] error:', e);
    }
}

function setProjectionMode(mode) {
    if (mode === 'mercator') {
        currentProjection = 'mercator';
    } else {
        currentProjection = 'globe';
    }
    applyProjection();
    updateStatus();
}

// ---------- Status ----------
function updateStatus() {
    var c = map.getCenter();
    var z = map.getZoom().toFixed(1);
    var modeLabel = currentProjection === 'globe' ? 'Globe' : 'Flat';
    document.getElementById('statusBox').textContent =
        'Center: [' + c.lng.toFixed(2) + ', ' + c.lat.toFixed(2) +
        '] | Zoom: ' + z + ' | Style: ' + currentBasemap +
        ' | Mode: ' + modeLabel;
}
map.on('move', updateStatus);
map.on('zoom', updateStatus);
map.on('load', function () {
    applyProjection();
    updateStatus();
    loadWelcomeMessage();
    console.log('[MAP] Map loaded, loading India border...');
    loadIndiaBorder();
});

function switchBasemap(styleName) {
    var styleObj = osmStyle;
    if (styleName === 'terrain') {
        styleObj = terrainStyle;
        currentBasemap = 'terrain';
    } else if (styleName === 'satellite') {
        styleObj = satelliteStyle;
        currentBasemap = 'satellite';
    } else {
        styleObj = osmStyle;
        currentBasemap = 'osm';
    }
    map.setStyle(styleObj);
    map.once('styledata', function () {
        applyProjection();
        updateStatus();
        setTimeout(function () {
            loadIndiaBorder();
        }, 200);
    });
}

// ---------- Route drawing ----------
function setRouteLine(coords) {
    if (!map.getSource('route')) {
        map.addSource('route', {
            "type": "geojson",
            "data": {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords
                }
            }
        });
        map.addLayer({
            "id": "route-line",
            "type": "line",
            "source": "route",
            "paint": {
                "line-width": 4,
                "line-color": "#22c55e"
            }
        });
    } else {
        map.getSource('route').setData({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords
            }
        });
    }
}

function clearRouteLine() {
    if (map.getLayer('route-line')) {
        map.removeLayer('route-line');
    }
    if (map.getSource('route')) {
        map.removeSource('route');
    }
}

// ---------- Measurement line ----------
function setMeasureLine(coords) {
    if (!map.getSource(MEASURE_SOURCE_ID)) {
        map.addSource(MEASURE_SOURCE_ID, {
            type: "geojson",
            data: {
                type: "Feature",
                geometry: {
                    type: "LineString",
                    coordinates: coords
                }
            }
        });
        map.addLayer({
            id: MEASURE_LINE_ID,
            type: "line",
            source: MEASURE_SOURCE_ID,
            paint: {
                "line-width": 3,
                "line-color": "#f97316",
                "line-dasharray": [2, 2]
            }
        });
    } else {
        map.getSource(MEASURE_SOURCE_ID).setData({
            type: "Feature",
            geometry: {
                type: "LineString",
                coordinates: coords
            }
        });
    }
}

function clearMeasureLine() {
    if (map.getLayer(MEASURE_LINE_ID)) {
        map.removeLayer(MEASURE_LINE_ID);
    }
    if (map.getSource(MEASURE_SOURCE_ID)) {
        map.removeSource(MEASURE_SOURCE_ID);
    }
}

// ---------- Detection layers ----------
function clearDetections() {
    var pairs = [
        [DET_RAIL_LAYER, DET_RAIL_SOURCE],
        [DET_ROAD_LAYER, DET_ROAD_SOURCE],
        [DET_BUILD_LAYER, DET_BUILD_SOURCE],
        [DET_WATER_LAYER, DET_WATER_SOURCE],
        [DET_GREEN_LAYER, DET_GREEN_SOURCE]
    ];
    pairs.forEach(function (pair) {
        var layerId = pair[0];
        var sourceId = pair[1];
        if (map.getLayer(layerId)) {
            map.removeLayer(layerId);
        }
        if (map.getSource(sourceId)) {
            map.removeSource(sourceId);
        }
    });
}

function setDetections(data) {
    clearDetections();

    var chkRail  = document.getElementById('chkDetRail');
    var chkRoad  = document.getElementById('chkDetRoad');
    var chkBuild = document.getElementById('chkDetBuild');
    var chkWater = document.getElementById('chkDetWater');
    var chkGreen = document.getElementById('chkDetGreen');

    var showRail  = chkRail  ? chkRail.checked  : true;
    var showRoad  = chkRoad  ? chkRoad.checked  : true;
    var showBuild = chkBuild ? chkBuild.checked : true;
    var showWater = chkWater ? chkWater.checked : true;
    var showGreen = chkGreen ? chkGreen.checked : true;

    if (data.railway_geojson && data.railway_geojson.features &&
        data.railway_geojson.features.length) {
        map.addSource(DET_RAIL_SOURCE, {
            type: "geojson",
            data: data.railway_geojson
        });
        map.addLayer({
            id: DET_RAIL_LAYER,
            type: "line",
            source: DET_RAIL_SOURCE,
            layout: {
                "visibility": showRail ? "visible" : "none"
            },
            paint: {
                "line-width": 2,
                "line-color": "#ef4444"
            }
        });
    }

    if (data.roads_geojson && data.roads_geojson.features &&
        data.roads_geojson.features.length) {
        map.addSource(DET_ROAD_SOURCE, {
            type: "geojson",
            data: data.roads_geojson
        });
        map.addLayer({
            id: DET_ROAD_LAYER,
            type: "line",
            source: DET_ROAD_SOURCE,
            layout: {
                "visibility": showRoad ? "visible" : "none"
            },
            paint: {
                "line-width": 1.5,
                "line-color": "#f97316"
            }
        });
    }

    if (data.buildings_geojson && data.buildings_geojson.features &&
        data.buildings_geojson.features.length) {
        map.addSource(DET_BUILD_SOURCE, {
            type: "geojson",
            data: data.buildings_geojson
        });
        map.addLayer({
            id: DET_BUILD_LAYER,
            type: "circle",
            source: DET_BUILD_SOURCE,
            layout: {
                "visibility": showBuild ? "visible" : "none"
            },
            paint: {
                "circle-radius": 2.5,
                "circle-color": "#e5e7eb",
                "circle-opacity": 0.8
            }
        });
    }

    if (data.waters_geojson && data.waters_geojson.features &&
        data.waters_geojson.features.length) {
        map.addSource(DET_WATER_SOURCE, {
            type: "geojson",
            data: data.waters_geojson
        });
        map.addLayer({
            id: DET_WATER_LAYER,
            type: "circle",
            source: DET_WATER_SOURCE,
            layout: {
                "visibility": showWater ? "visible" : "none"
            },
            paint: {
                "circle-radius": 3,
                "circle-color": "#22d3ee",
                "circle-opacity": 0.8
            }
        });
    }

    if (data.greens_geojson && data.greens_geojson.features &&
        data.greens_geojson.features.length) {
        map.addSource(DET_GREEN_SOURCE, {
            type: "geojson",
            data: data.greens_geojson
        });
        map.addLayer({
            id: DET_GREEN_LAYER,
            type: "circle",
            source: DET_GREEN_SOURCE,
            layout: {
                "visibility": showGreen ? "visible" : "none"
            },
            paint: {
                "circle-radius": 2.5,
                "circle-color": "#22c55e",
                "circle-opacity": 0.8
            }
        });
    }
}

function onDetLayerToggle(type, visible) {
    var layerId = DET_LAYER_IDS[type];
    if (!layerId) return;
    if (!map.getLayer(layerId)) return;
    map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
}

// ---------- India Border GeoJSON ----------
const INDIA_BORDER_SOURCE = 'india-border';
const INDIA_BORDER_LINE_LAYER = 'india-border-line';
const INDIA_BORDER_FILL_LAYER = 'india-border-fill';

function onIndiaBorderToggle(visible) {
    var visibility = visible ? "visible" : "none";
    if (map.getLayer(INDIA_BORDER_LINE_LAYER)) {
        map.setLayoutProperty(INDIA_BORDER_LINE_LAYER, "visibility", visibility);
    }
    console.log("[INDIA_BORDER] Border outline visibility toggled to:", visibility);
}

function loadIndiaBorder() {
    console.log('[INDIA_BORDER] Starting to load border, map loaded:', map.loaded());

    if (!map || !map.loaded()) {
        console.log('[INDIA_BORDER] Map not ready, waiting for load event...');
        if (map) {
            map.once('load', loadIndiaBorder);
        }
        return;
    }

    var dataPromise;
    if (typeof INDIA_BORDER_DATA !== 'undefined' && INDIA_BORDER_DATA) {
        console.log('[INDIA_BORDER] Using embedded GeoJSON data');
        dataPromise = Promise.resolve(INDIA_BORDER_DATA);
    } else {
        console.log('[INDIA_BORDER] Fetching border data from /api/india-border');
        dataPromise = fetch('/api/india-border')
            .then(function (res) {
                console.log('[INDIA_BORDER] Response status:', res.status, res.statusText);
                if (!res.ok) {
                    throw new Error('HTTP ' + res.status + ': ' + res.statusText);
                }
                return res.json();
            });
    }

    dataPromise
        .then(function (data) {
            var featureCount =
                data && data.features && data.features.length
                    ? data.features.length
                    : 0;

            console.log(
                '[INDIA_BORDER] Received data, type:',
                data && data.type,
                'features:',
                featureCount
            );

            if (!data || !data.features || !data.features.length) {
                console.error('[INDIA_BORDER] No border data available!');
                return;
            }

            try {
                if (map.getLayer(INDIA_BORDER_LINE_LAYER)) {
                    map.removeLayer(INDIA_BORDER_LINE_LAYER);
                }
                if (map.getLayer(INDIA_BORDER_FILL_LAYER)) {
                    map.removeLayer(INDIA_BORDER_FILL_LAYER);
                }
                if (map.getSource(INDIA_BORDER_SOURCE)) {
                    map.removeSource(INDIA_BORDER_SOURCE);
                }
            } catch (e) {
                console.warn('[INDIA_BORDER] Error removing existing layers:', e.message);
            }

            try {
                map.addSource(INDIA_BORDER_SOURCE, {
                    type: 'geojson',
                    data: data
                });
                console.log('[INDIA_BORDER] ✓ Source added');
            } catch (e) {
                console.error('[INDIA_BORDER] ✗ Error adding source:', e);
                return;
            }

            try {
                map.addLayer({
                    id: INDIA_BORDER_LINE_LAYER,
                    type: 'line',
                    source: INDIA_BORDER_SOURCE,
                    paint: {
                        'line-width': 1.5,
                        'line-color': '#000000',
                        'line-opacity': 1.0
                    }
                });
                console.log('[INDIA_BORDER] ✓ Line layer added (outline only)');
            } catch (e) {
                console.error('[INDIA_BORDER] ✗ Error adding line layer:', e);
                console.error('[INDIA_BORDER] Error details:', e.message, e.stack);
            }

            var checkbox = document.getElementById('chkIndiaBorder');
            if (checkbox && !checkbox.checked) {
                onIndiaBorderToggle(false);
                console.log('[INDIA_BORDER] Border hidden (checkbox unchecked)');
            } else {
                console.log('[INDIA_BORDER] Border visible (checkbox checked)');
            }

            setTimeout(function () {
                var hasLine = !!map.getLayer(INDIA_BORDER_LINE_LAYER);
                var hasSource = !!map.getSource(INDIA_BORDER_SOURCE);
                console.log('[INDIA_BORDER] Final check - Line:', hasLine, 'Source:', hasSource);
            }, 300);
        })
        .catch(function (err) {
            console.error('[INDIA_BORDER] ✗ Fetch error:', err);
        });
}

// ---------- Chat panel ----------
function addMessage(role, text) {
    var wrap = document.getElementById('messages');
    var row = document.createElement('div');
    row.className = 'message-row ' + role;
    var bubble = document.createElement('div');
    bubble.className = 'message ' + (role === 'user' ? 'user' : 'assistant');
    bubble.textContent = text;
    row.appendChild(bubble);
    wrap.appendChild(row);
    wrap.scrollTop = wrap.scrollHeight;
}

function runQuick(text) {
    var input = document.getElementById('queryInput');
    input.value = text;
    sendQuery();
}

async function loadWelcomeMessage() {
    try {
        var center = map.getCenter();
        var payload = {
            query: "hello",
            center: { lng: center.lng, lat: center.lat },
            zoom: map.getZoom()
        };
        var res = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        var data = await res.json();
        if (data.message) addMessage('assistant', data.message);
    } catch (e) {
        console.error(e);
        addMessage('assistant', 'Error loading welcome message.');
    }
}

async function sendQuery() {
    var input = document.getElementById('queryInput');
    var btn = document.getElementById('sendBtn');
    var text = input.value.trim();
    if (!text) return;
    addMessage('user', text);
    input.value = '';

    var oldLabel = btn.textContent;
    btn.textContent = 'Sending...';
    btn.disabled = true;

    var center = map.getCenter();
    var payload = {
        query: text,
        center: { lng: center.lng, lat: center.lat },
        zoom: map.getZoom()
    };

    try {
        var res = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (res.status === 429) {
            addMessage('assistant', 'Rate limit reached. Please wait a bit before sending more queries.');
            return;
        }
        var data = await res.json();
        if (data.message) addMessage('assistant', data.message);
        if (data.action) handleAction(data.action);
    } catch (e) {
        console.error(e);
        addMessage('assistant', 'Error talking to server.');
    } finally {
        btn.textContent = oldLabel;
        btn.disabled = false;
        input.focus();
    }
}

function handleAction(action) {
    if (!action || !action.type) return;
    switch (action.type) {
        case 'flyTo':
            map.flyTo({
                center: action.center,
                zoom: action.zoom || 13,
                pitch: action.pitch || 0,
                duration: 1500
            });
            break;
        case 'reset':
            clearRouteLine();
            clearMeasureLine();
            clearDetections();
            map.flyTo({
                center: [78.9629, 20.5937],
                zoom: 4.2,
                pitch: 50,
                bearing: 0,
                duration: 1500
            });
            break;
        case 'setStyle':
            switchBasemap(action.style || 'osm');
            break;
        case 'setRoute':
            clearMeasureLine();
            if (action.center) {
                map.flyTo({
                    center: action.center,
                    zoom: action.zoom || 9,
                    pitch: 0,
                    duration: 1500
                });
            }
            if (action.coords) {
                setRouteLine(action.coords);
            }
            break;
        case 'clearRoute':
            clearRouteLine();
            break;
        case 'measureDistance':
            clearMeasureLine();
            if (action.from && action.to) {
                setMeasureLine([action.from, action.to]);
            }
            break;
        case 'setDetections':
            if (action.data) {
                setDetections(action.data);
            }
            if (action.center) {
                map.flyTo({
                    center: action.center,
                    zoom: 15,
                    pitch: 0,
                    duration: 1200
                });
            }
            break;
    }
}

// Auto-focus
window.addEventListener('load', function () {
    var input = document.getElementById('queryInput');
    if (input) input.focus();
});
</script></body></html>"""

ABOUT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>About – GEO AI Map</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
body {
    margin:0; padding:20px;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background:#020617; color:#e5e7eb;
}
a { color:#93c5fd; text-decoration:none; }
.card {
    max-width:720px;
    margin:0 auto;
    background:#020617;
    border-radius:16px;
    border:1px solid #1f2937;
    padding:20px;
}
</style>
</head>
<body>
<div class="card">
    <h1>GEO AI Map</h1>
    <p>This experimental interface combines:</p>
    <ul>
        <li>MapLibre GL + OpenStreetMap basemaps</li>
        <li>Routing via OSRM public API</li>
        <li>Weather via Open-Meteo</li>
        <li>Object detection & POIs via Overpass API</li>
        <li>Optional TinyLlama-based natural language rephrasing</li>
    </ul>
    <p>Powered by IIT Tirupati Navavishkar I-Hub Foundation (IITTNiF).</p>
    <p><a href="/">← Back to map</a></p>
</div></body></html>"""

# ================== Flask routes ================== #
@app.route("/")
def index():
    # Load India border GeoJSON and embed it in the template
    geojson_path = os.path.join(os.path.dirname(__file__), "india_border.geojson")
    india_geojson_data = {"type": "FeatureCollection", "features": []}
    if os.path.exists(geojson_path):
        try:
            with open(geojson_path, "r", encoding="utf-8") as f:
                india_geojson_data = json.load(f)
            print(
                f"[INDIA_BORDER] Loaded {len(india_geojson_data.get('features', []))} features for template"
            )
        except Exception as e:
            print(f"[INDIA_BORDER] Error loading for template: {e}")

    injection = "const INDIA_BORDER_DATA = " + json.dumps(india_geojson_data) + ";"
    template_with_data = MAIN_TEMPLATE.replace("//__INDIA_BORDER_DATA__", injection)
    return render_template_string(template_with_data)

@app.route("/about")
def about():
    return render_template_string(ABOUT_TEMPLATE)

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)

@app.route("/api/query", methods=["POST"])
def api_query():
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip):
        return jsonify({"message": "Rate limit exceeded."}), 429

    data = request.json or {}
    query = data.get("query", "")
    center = data.get("center")
    zoom = data.get("zoom")
    resp = process_query(query, center=center, zoom=zoom) or {}

    msg = resp.get("message")
    if msg and ENABLE_TINYLLAMA:
        resp["raw_message"] = msg
        resp["message"] = humanize_message(query, msg)

    return jsonify(resp)

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/india-border")
def india_border():
    geojson_path = os.path.join(os.path.dirname(__file__), "india_border.geojson")
    print(f"[INDIA_BORDER] Looking for file at: {geojson_path}")
    if os.path.exists(geojson_path):
        try:
            with open(geojson_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            feature_count = len(data.get("features", [])) if isinstance(data, dict) else 0
            print(f"[INDIA_BORDER] Successfully loaded {feature_count} features")
            return jsonify(data)
        except Exception as e:
            print(f"[INDIA_BORDER] Error loading GeoJSON: {e}")
            return jsonify({"type": "FeatureCollection", "features": []}), 200
    else:
        print(f"[INDIA_BORDER] File not found: {geojson_path}")
        print(f"[INDIA_BORDER] Current directory: {os.getcwd()}")
        return jsonify({"type": "FeatureCollection", "features": []}), 200

if __name__ == "__main__":
    print("🌍 Running GEO AI Map (MapLibre + OSM + weather + routes + detection + TinyLlama + Globe/Flat)")
    debug_mode = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    port = int(os.getenv("FLASK_PORT", "3000"))
    app.run(debug=debug_mode, host="0.0.0.0", port=port)