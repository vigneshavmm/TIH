#!/usr/bin/env python3
"""geo_agent_v2.py  —  GeoAI Intelligence Agent (Real-Time Edition)
Conversational Text → LLM → Live GIS Data → Interactive 3D Map

Real-Time Data Sources:
  Weather/Rain : Open-Meteo  (no key)
  Disasters    : GDACS RSS + ReliefWeb API (no key)
  Air Quality  : OpenAQ v3 (no key)
  Live Traffic : OSM Overpass API (no key)
  DEM / Elev   : opentopodata.org SRTM 30m (no key)
  OSM Vectors  : osmnx + Overpass

Viz:
  2D Layers    : Folium + CartoDB Dark
  3D Terrain   : deck.gl TerrainLayer (SRTM RGB tiles)

UI:
  Conversational chat panel with intent echo, session memory,
  follow-up suggestion chips, multi-turn context"""

# 01 | IMPORTS
import json, os, time, threading, traceback, hashlib, re
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import numpy as np
import requests
import geopandas as gpd
import folium
from folium.plugins import HeatMap, MiniMap, Fullscreen, MarkerCluster
from shapely.geometry import box, Point
from flask import Flask, render_template_string, jsonify, request
from flask_socketio import SocketIO, emit

try:
    import osmnx as ox
    ox.settings.log_console = False
    ox.settings.use_cache   = True
    OSMNX_OK = True
except ImportError:
    OSMNX_OK = False

# 02 | CONFIG
CFG = {
    "HOST"            : "0.0.0.0",
    "PORT"            : 5000,
    "DEBUG"           : False,
    # LLM
    "OLLAMA_URL"      : "http://localhost:11434/api/generate",
    "OLLAMA_CHAT_URL" : "http://localhost:11434/api/chat",
    "OLLAMA_MODEL"    : "mistral",
    "LLM_TEMPERATURE" : 0.05,
    "LLM_MAX_TOKENS"  : 768,
    # Agent
    "MAX_AGENT_STEPS" : 14,
    # DEM
    "ELEV_API"        : "https://api.opentopodata.org/v1/srtm30m",
    "ELEV_BATCH"      : 100,
    "ELEV_RATE_SLEEP" : 0.4,
    # Real-time APIs (no keys)
    "OPENMETEO_URL"   : "https://api.open-meteo.com/v1/forecast",
    "OPENAQ_URL"      : "https://api.openaq.org/v3/locations",
    "GDACS_RSS"       : "https://www.gdacs.org/xml/rss.xml",
    "RELIEFWEB_URL"   : "https://api.reliefweb.int/v1/disasters",
    "OVERPASS_URL"    : "https://overpass-api.de/api/interpreter",
    # Map
    "MAP_PATH"        : "static/map_output.html",
    "MAP_3D_PATH"     : "static/map_3d.html",
    "MAP_ZOOM"        : 12,
    # Colors
    "TEAL"            : "#00d4a0",
    "BG"              : "#0a0e14",
}

# 03 | FLASK + SOCKETIO
app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = "geoagent_v2_2025"
sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
os.makedirs("static", exist_ok=True)

# 04 | TOOL REGISTRY
TOOL_REGISTRY: Dict[str, Dict] = {}

def tool(name: str, description: str, params: Dict[str, str]):
    def decorator(fn):
        TOOL_REGISTRY[name] = {
            "name": name, "description": description,
            "params": params, "fn": fn,
        }
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def tools_schema_str() -> str:
    lines = []
    for name, t in TOOL_REGISTRY.items():
        param_str = ", ".join(f"{k}: {v}" for k, v in t["params"].items())
        lines.append(f"  {name}({param_str})\n    → {t['description']}")
    return "\n".join(lines)

# 05 | AGENT STATE + CONVERSATION MEMORY
STATE: Dict[str, Any] = {
    "running"         : False,
    "map_ready"       : False,
    "map_3d_ready"    : False,
    "query"           : "",
    "steps"           : [],
    "ctx"             : {},
    "conversation"    : [],   # multi-turn chat history
    "session_memory"  : {},   # persists across turns: last place, preferences
    "active_layers"   : [],
}

def log(level: str, tool_name: str, msg: str, data: Any = None):
    entry = {
        "ts"   : datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "level": level,
        "tool" : tool_name,
        "msg"  : msg,
        "data" : data,
    }
    STATE["steps"].append(entry)
    sio.emit("agent_step", entry)

def chat_push(role: str, text: str, meta: Dict = None):
    """Add a message to the conversational UI chat."""
    entry = {
        "id"   : hashlib.md5(f"{role}{time.time()}".encode()).hexdigest()[:8],
        "role" : role,
        "text" : text,
        "ts"   : datetime.now().strftime("%H:%M"),
        "meta" : meta or {},
    }
    STATE["conversation"].append(entry)
    sio.emit("chat_message", entry)
    return entry

# 06 | GIS TOOLS — CORE
@tool(
    name        = "geocode_place",
    description = "Geocode a place name → bounding box + center lat/lon. Always call first.",
    params      = {"place_name": "string — city, district, or region name"}
)
def geocode_place(place_name: str) -> Dict:
    log("info", "geocode_place", f"Geocoding → {place_name}")
    if not OSMNX_OK:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": place_name, "format": "json", "limit": 1},
            headers={"User-Agent": "GeoAgent/2.0"},
            timeout=15,
        )
        data = r.json()
        if not data:
            raise ValueError(f"Could not geocode: {place_name}")
        d = data[0]
        lat, lon = float(d["lat"]), float(d["lon"])
        delta = 0.2
        bbox = {"west": lon-delta, "south": lat-delta, "east": lon+delta, "north": lat+delta}
        center = [lat, lon]
    else:
        gdf    = ox.geocode_to_gdf(place_name)
        bounds = gdf.total_bounds
        center = [(bounds[1]+bounds[3])/2, (bounds[0]+bounds[2])/2]
        bbox   = {"west": bounds[0], "south": bounds[1], "east": bounds[2], "north": bounds[3]}

    result = {"place": place_name, "center": center, "bbox": bbox}
    STATE["ctx"]["geocode"] = result
    STATE["session_memory"]["last_place"]  = place_name
    STATE["session_memory"]["last_center"] = center
    STATE["session_memory"]["last_bbox"]   = bbox

    log("success", "geocode_place",
        f"Center: {center[0]:.4f}°N  {center[1]:.4f}°E", bbox)
    return result


@tool(
    name        = "fetch_osm_features",
    description = "Fetch OpenStreetMap vector features for the current area.",
    params      = {
        "place_name"  : "string — same place as geocode_place",
        "feature_type": "string — OSM tag e.g. 'waterway', 'natural=water', 'highway', 'landuse=residential'",
    }
)
def fetch_osm_features(place_name: str, feature_type: str) -> Dict:
    log("info", "fetch_osm_features", f"OSM fetch → {feature_type} in {place_name}")
    if not OSMNX_OK:
        log("warning", "fetch_osm_features", "osmnx not installed — skipping")
        return {"feature_type": feature_type, "count": 0, "key": "skipped"}

    if "=" in feature_type:
        k, v = feature_type.split("=", 1)
        tags = {k.strip(): v.strip()}
    else:
        tags = {feature_type.strip(): True}

    try:
        gdf = ox.features_from_place(place_name, tags=tags)
        gdf = gdf.to_crs("EPSG:4326")
    except Exception as e:
        log("warning", "fetch_osm_features", f"No features found: {e}")
        return {"feature_type": feature_type, "count": 0, "key": "none"}

    safe_key = feature_type.replace("=", "_").replace(" ", "_")
    STATE["ctx"].setdefault("osm_features", {})[safe_key] = gdf
    log("success", "fetch_osm_features", f"{len(gdf)} features [{feature_type}]",
        {"count": len(gdf), "key": safe_key})
    return {"feature_type": feature_type, "count": len(gdf), "key": safe_key}


@tool(
    name        = "fetch_elevation_grid",
    description = "Download SRTM 30m elevation grid. Required before flood analysis, slope, or 3D terrain.",
    params      = {"resolution": "int — grid size N×N, 10–30, default 20"}
)
def fetch_elevation_grid(resolution: int = 20) -> Dict:
    geo = STATE["ctx"].get("geocode")
    if not geo:
        raise ValueError("Call geocode_place first.")

    resolution = max(10, min(30, int(resolution)))
    log("info", "fetch_elevation_grid", f"Fetching DEM {resolution}×{resolution}...")

    bbox = geo["bbox"]
    lats = np.linspace(bbox["south"], bbox["north"], resolution)
    lons = np.linspace(bbox["west"],  bbox["east"],  resolution)
    points = [(lat, lon) for lat in lats for lon in lons]
    elevations: List[float] = []

    for i in range(0, len(points), CFG["ELEV_BATCH"]):
        batch = points[i : i + CFG["ELEV_BATCH"]]
        loc_str = "|".join(f"{lat},{lon}" for lat, lon in batch)
        try:
            resp = requests.get(CFG["ELEV_API"],
                                params={"locations": loc_str}, timeout=30)
            for r in resp.json().get("results", []):
                elevations.append(float(r.get("elevation") or 0.0))
        except Exception as e:
            log("warning", "fetch_elevation_grid", f"Batch {i} failed: {e}")
            elevations.extend([0.0] * len(batch))
        time.sleep(CFG["ELEV_RATE_SLEEP"])
        log("info", "fetch_elevation_grid",
            f"  {min(i+CFG['ELEV_BATCH'], len(points))}/{len(points)} points")

    grid = np.array(elevations).reshape(resolution, resolution)
    STATE["ctx"]["elevation"] = {
        "grid": grid.tolist(), "lats": lats.tolist(), "lons": lons.tolist(),
        "resolution": resolution,
        "min": float(grid.min()), "max": float(grid.max()),
        "mean": float(grid.mean()),
        "p10": float(np.percentile(grid, 10)),
        "p20": float(np.percentile(grid, 20)),
    }
    log("success", "fetch_elevation_grid",
        f"Elevation: {grid.min():.1f}m – {grid.max():.1f}m (mean {grid.mean():.1f}m)",
        {"min": grid.min(), "max": grid.max(), "mean": grid.mean()})
    return STATE["ctx"]["elevation"]


@tool(
    name        = "analyze_flood_prone",
    description = "Identify flood-prone zones from DEM. Low elevation + flat terrain = high risk.",
    params      = {"threshold_percentile": "int — elevation percentile for flood threshold (10–35, default 20)"}
)
def analyze_flood_prone(threshold_percentile: int = 20) -> Dict:
    elev_ctx = STATE["ctx"].get("elevation")
    if not elev_ctx:
        raise ValueError("Call fetch_elevation_grid first.")

    threshold_percentile = max(5, min(40, int(threshold_percentile)))
    log("info", "analyze_flood_prone", f"Flood analysis — threshold: {threshold_percentile}th pct")

    grid = np.array(elev_ctx["grid"])
    lats = elev_ctx["lats"]
    lons = elev_ctx["lons"]
    res  = elev_ctx["resolution"]
    thresh = np.percentile(grid, threshold_percentile)

    cell_h = (lats[-1] - lats[0]) / res
    cell_w = (lons[-1] - lons[0]) / res
    polys, risks, elevs = [], [], []

    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            elev = grid[i, j]
            if elev <= thresh:
                polys.append(box(lon - cell_w/2, lat - cell_h/2,
                                 lon + cell_w/2, lat + cell_h/2))
                raw  = thresh - elev
                span = max(thresh - grid.min(), 1e-6)
                risks.append(float(np.clip(raw / span, 0, 1)))
                elevs.append(float(elev))

    gdf = gpd.GeoDataFrame({"risk": risks, "elevation_m": elevs, "geometry": polys}, crs="EPSG:4326")
    STATE["ctx"]["flood_zones"]     = gdf
    STATE["ctx"]["flood_threshold"] = float(thresh)
    log("success", "analyze_flood_prone",
        f"{len(gdf)} flood-prone cells | threshold < {thresh:.1f}m",
        {"cells": len(gdf), "threshold_m": thresh})
    return {"flood_cell_count": len(gdf), "threshold_elevation_m": float(thresh)}


@tool(
    name        = "compute_slope",
    description = "Compute terrain slope magnitude from DEM gradient.",
    params      = {}
)
def compute_slope() -> Dict:
    elev_ctx = STATE["ctx"].get("elevation")
    if not elev_ctx:
        raise ValueError("Call fetch_elevation_grid first.")
    log("info", "compute_slope", "Computing slope from DEM gradient...")

    grid = np.array(elev_ctx["grid"])
    lats = elev_ctx["lats"]
    lons = elev_ctx["lons"]
    res  = elev_ctx["resolution"]
    dy, dx    = np.gradient(grid)
    slope_mag = np.sqrt(dx**2 + dy**2)
    span      = max(slope_mag.max() - slope_mag.min(), 1e-6)
    slope_norm = (slope_mag - slope_mag.min()) / span

    cell_h = (lats[-1] - lats[0]) / res
    cell_w = (lons[-1] - lons[0]) / res
    polys, vals = [], []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            s = float(slope_norm[i, j])
            if s > 0.05:
                polys.append(box(lon - cell_w/2, lat - cell_h/2,
                                 lon + cell_w/2, lat + cell_h/2))
                vals.append(s)

    gdf = gpd.GeoDataFrame({"slope_norm": vals, "geometry": polys}, crs="EPSG:4326")
    STATE["ctx"]["slope_zones"] = gdf
    log("success", "compute_slope", f"{len(gdf)} slope cells computed")
    return {"slope_cells": len(gdf)}

# 06b | REAL-TIME DATA TOOLS
@tool(
    name        = "fetch_weather_realtime",
    description = "Fetch live weather + rainfall forecast from Open-Meteo for the geocoded location. No API key needed.",
    params      = {"hours_ahead": "int — forecast hours, 24–168, default 48"}
)
def fetch_weather_realtime(hours_ahead: int = 48) -> Dict:
    geo = STATE["ctx"].get("geocode")
    if not geo:
        raise ValueError("Call geocode_place first.")

    lat, lon = geo["center"]
    hours_ahead = max(24, min(168, int(hours_ahead)))

    log("info", "fetch_weather_realtime", f"Open-Meteo → {lat:.4f},{lon:.4f}  (+{hours_ahead}h)")

    params = {
        "latitude" : lat,
        "longitude": lon,
        "hourly"   : "temperature_2m,precipitation,precipitation_probability,"
                     "windspeed_10m,cloudcover,weathercode",
        "daily"    : "precipitation_sum,temperature_2m_max,temperature_2m_min",
        "forecast_days": min(7, hours_ahead // 24 + 1),
        "timezone" : "auto",
    }
    try:
        resp = requests.get(CFG["OPENMETEO_URL"], params=params, timeout=20)
        data = resp.json()
    except Exception as e:
        log("warning", "fetch_weather_realtime", f"Open-Meteo failed: {e}")
        return {"error": str(e)}

    hourly = data.get("hourly", {})
    daily  = data.get("daily",  {})

    # Compute rainfall alert
    precip_vals = hourly.get("precipitation", [])
    max_rain    = max(precip_vals[:hours_ahead], default=0)
    rain_alert  = "HIGH" if max_rain > 15 else ("MODERATE" if max_rain > 5 else "LOW")

    result = {
        "current_temp_c"    : hourly.get("temperature_2m", [None])[0],
        "max_rain_mm_per_h" : round(max_rain, 2),
        "rain_alert_level"  : rain_alert,
        "daily_precip_sum"  : daily.get("precipitation_sum", [])[:7],
        "daily_temp_max"    : daily.get("temperature_2m_max", [])[:7],
        "daily_temp_min"    : daily.get("temperature_2m_min", [])[:7],
        "hourly_precip"     : precip_vals[:hours_ahead],
        "hourly_time"       : hourly.get("time", [])[:hours_ahead],
        "hourly_windspeed"  : hourly.get("windspeed_10m", [])[:hours_ahead],
        "hourly_cloud"      : hourly.get("cloudcover",    [])[:hours_ahead],
    }
    STATE["ctx"]["weather"] = result
    log("success", "fetch_weather_realtime",
        f"Rain alert: {rain_alert} | Max rain: {max_rain:.1f}mm/h",
        {"max_rain_mm": max_rain, "alert": rain_alert})
    return result

@tool(
    name        = "fetch_disaster_alerts",
    description = "Fetch live global disaster alerts from GDACS RSS and ReliefWeb API. Shows floods, storms, earthquakes near the location.",
    params      = {"radius_km": "int — search radius around location in km, 50–500, default 200"}
)
def fetch_disaster_alerts(radius_km: int = 200) -> Dict:
    geo = STATE["ctx"].get("geocode")
    if not geo:
        raise ValueError("Call geocode_place first.")

    lat, lon = geo["center"]
    radius_km = max(50, min(500, int(radius_km)))
    log("info", "fetch_disaster_alerts", f"GDACS+ReliefWeb → radius {radius_km}km")

    alerts = []

    # --- GDACS RSS ---
    try:
        resp = requests.get(CFG["GDACS_RSS"], timeout=20,
                            headers={"User-Agent": "GeoAgent/2.0"})
        root = ET.fromstring(resp.content)
        ns   = {
            "gdacs": "http://www.gdacs.org",
            "geo"  : "http://www.w3.org/2003/01/geo/wgs84_pos#",
        }
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            link  = item.findtext("link", "")
            pubdate = item.findtext("pubDate", "")

            # Try to extract coordinates
            glat_el = item.find(".//geo:lat",   ns)
            glon_el = item.find(".//geo:long",  ns)
            alert_type = item.findtext("{http://www.gdacs.org}eventtype", "")
            severity   = item.findtext("{http://www.gdacs.org}alertlevel", "")

            if glat_el is not None and glon_el is not None:
                alat = float(glat_el.text)
                alon = float(glon_el.text)
                # Rough distance filter (1 deg ≈ 111 km)
                dist_deg = ((alat - lat)**2 + (alon - lon)**2) ** 0.5
                dist_km  = dist_deg * 111
                if dist_km <= radius_km:
                    alerts.append({
                        "source"  : "GDACS",
                        "title"   : title,
                        "type"    : alert_type,
                        "severity": severity,
                        "lat"     : alat,
                        "lon"     : alon,
                        "dist_km" : round(dist_km, 1),
                        "date"    : pubdate,
                        "link"    : link,
                    })
    except Exception as e:
        log("warning", "fetch_disaster_alerts", f"GDACS failed: {e}")

    # --- ReliefWeb ---
    try:
        # Build bounding box from radius
        deg = radius_km / 111.0
        rw_params = {
            "appname": "GeoAgent",
            "fields[include][]": ["name", "date", "type", "status", "country"],
            "filter[operator]": "AND",
            "filter[conditions][0][field]": "status",
            "filter[conditions][0][value]": "alert",
            "limit": 10,
            "sort[]": "date:desc",
        }
        rw_resp = requests.get(CFG["RELIEFWEB_URL"], params=rw_params, timeout=15)
        rw_data = rw_resp.json()
        for item in rw_data.get("data", []):
            fields = item.get("fields", {})
            alerts.append({
                "source"  : "ReliefWeb",
                "title"   : fields.get("name", ""),
                "type"    : (fields.get("type") or [{}])[0].get("name", ""),
                "severity": fields.get("status", ""),
                "lat"     : None,
                "lon"     : None,
                "dist_km" : None,
                "date"    : (fields.get("date") or {}).get("created", ""),
                "link"    : "",
            })
    except Exception as e:
        log("warning", "fetch_disaster_alerts", f"ReliefWeb failed: {e}")

    STATE["ctx"]["disaster_alerts"] = alerts
    log("success", "fetch_disaster_alerts",
        f"{len(alerts)} disaster alerts found",
        {"count": len(alerts)})
    return {"alert_count": len(alerts), "alerts": alerts[:5]}


@tool(
    name        = "fetch_air_quality",
    description = "Fetch real-time air quality data from OpenAQ for the nearest monitoring stations.",
    params      = {"radius_km": "int — search radius for AQ stations, 25–150, default 50"}
)
def fetch_air_quality(radius_km: int = 50) -> Dict:
    geo = STATE["ctx"].get("geocode")
    if not geo:
        raise ValueError("Call geocode_place first.")

    lat, lon = geo["center"]
    radius_km = max(25, min(150, int(radius_km)))
    log("info", "fetch_air_quality", f"OpenAQ → {lat:.3f},{lon:.3f} r={radius_km}km")

    try:
        resp = requests.get(
            CFG["OPENAQ_URL"],
            params={
                "coordinates": f"{lat},{lon}",
                "radius"     : radius_km * 1000,
                "limit"      : 10,
                "order_by"   : "distance",
            },
            headers={"X-API-Key": ""},
            timeout=20,
        )
        data = resp.json()
        stations = []
        for loc in data.get("results", []):
            coords   = loc.get("coordinates", {}) or {}
            sensors  = [s.get("parameter", {}).get("name", "") for s in loc.get("sensors", [])]
            stations.append({
                "name"      : loc.get("name", ""),
                "lat"       : coords.get("latitude"),
                "lon"       : coords.get("longitude"),
                "city"      : (loc.get("locality") or ""),
                "sensors"   : sensors,
                "last_updated": loc.get("datetimeLast", {}).get("local", "") if isinstance(loc.get("datetimeLast"), dict) else "",
                "distance_m": loc.get("distance", None),
            })

        STATE["ctx"]["air_quality"] = {"stations": stations, "radius_km": radius_km}
        log("success", "fetch_air_quality",
            f"{len(stations)} AQ stations found",
            {"stations": len(stations)})
        return {"station_count": len(stations), "stations": stations}

    except Exception as e:
        log("warning", "fetch_air_quality", f"OpenAQ failed: {e}")
        return {"station_count": 0, "error": str(e)}


@tool(
    name        = "fetch_live_traffic",
    description = "Fetch live road network and traffic conditions via OSM Overpass API.",
    params      = {
        "place_name"  : "string — area to query",
        "road_type"   : "string — 'primary', 'secondary', 'motorway', or 'all'",
    }
)
def fetch_live_traffic(place_name: str, road_type: str = "primary") -> Dict:
    geo = STATE["ctx"].get("geocode")
    if not geo:
        raise ValueError("Call geocode_place first.")

    bbox = geo["bbox"]
    log("info", "fetch_live_traffic", f"Overpass → {road_type} roads in {place_name}")

    if road_type == "all":
        highway_filter = '["highway"~"motorway|trunk|primary|secondary"]'
    else:
        highway_filter = f'["highway"="{road_type}"]'

    overpass_query = f"""
    [out:json][timeout:25];
    (
      way{highway_filter}
        ({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
    );
    out body geom;
    """

    try:
        resp = requests.post(
            CFG["OVERPASS_URL"],
            data={"data": overpass_query},
            timeout=30,
        )
        elements = resp.json().get("elements", [])

        roads = []
        for el in elements:
            if el.get("type") == "way" and "geometry" in el:
                coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
                tags   = el.get("tags", {})
                roads.append({
                    "id"     : el["id"],
                    "name"   : tags.get("name", ""),
                    "highway": tags.get("highway", ""),
                    "coords" : coords,
                    "maxspeed": tags.get("maxspeed", ""),
                })

        STATE["ctx"]["traffic_roads"] = roads
        log("success", "fetch_live_traffic",
            f"{len(roads)} road segments fetched",
            {"count": len(roads)})
        return {"road_count": len(roads), "road_type": road_type}

    except Exception as e:
        log("warning", "fetch_live_traffic", f"Overpass failed: {e}")
        return {"road_count": 0, "error": str(e)}

# 06c | RENDER TOOLS
@tool(
    name        = "render_map",
    description = "Generate the Folium 2D interactive map from all computed layers. Call this for 2D output.",
    params      = {
        "title" : "string — map title",
        "layers": "list of strings — choose from: flood_zones, elevation_heatmap, slope, osm_water, osm_roads, weather_overlay, disaster_markers, air_quality_markers, traffic_roads",
    }
)
def render_map(title: str = "GeoAI Analysis", layers: List[str] = None) -> Dict:
    if layers is None:
        layers = ["elevation_heatmap"]

    geo    = STATE["ctx"].get("geocode", {})
    center = geo.get("center", [13.6288, 79.4192])

    log("info", "render_map", f"Rendering 2D map | layers: {layers}")

    m = folium.Map(location=center, zoom_start=CFG["MAP_ZOOM"], tiles=None)

    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        attr="CartoDB", name="Dark (default)",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OSM", show=False).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite", show=False,
    ).add_to(m)

    # ── Elevation heatmap ──────────────────────────────────────────
    if "elevation_heatmap" in layers and "elevation" in STATE["ctx"]:
        ec   = STATE["ctx"]["elevation"]
        grid = np.array(ec["grid"])
        lats = ec["lats"]
        lons = ec["lons"]
        span = max(grid.max() - grid.min(), 1.0)
        heat_data = [
            [lats[i], lons[j], float((grid[i, j] - grid.min()) / span)]
            for i in range(len(lats)) for j in range(len(lons))
        ]
        HeatMap(heat_data, name="Elevation Heatmap", radius=20, blur=14,
                gradient={"0.0": "#001f3f", "0.25": "#0074d9",
                          "0.5": "#2ecc71", "0.75": "#f0a500", "1.0": "#ff4136"},
                show=True).add_to(m)

    # ── Flood zones ────────────────────────────────────────────────
    if "flood_zones" in layers and "flood_zones" in STATE["ctx"]:
        flood_gdf = STATE["ctx"]["flood_zones"]
        thresh    = STATE["ctx"].get("flood_threshold", 0)
        flood_layer = folium.FeatureGroup(name="Flood-Prone Zones", show=True)
        for _, row in flood_gdf.iterrows():
            r_val = float(row["risk"])
            red   = int(80 + r_val * 175)
            blue  = int(max(0, 80 - r_val * 60))
            color = f"#{red:02x}2a{blue:02x}"
            alpha = min(0.75, 0.35 + r_val * 0.4)
            feature_dict = {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {
                    "risk": round(r_val, 3),
                    "elevation_m": round(float(row["elevation_m"]), 1),
                },
            }
            folium.GeoJson(
                feature_dict,
                style_function=lambda feat, c=color, a=alpha: {
                    "fillColor": c, "color": "none",
                    "fillOpacity": a, "weight": 0,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["risk", "elevation_m"],
                    aliases=["Risk score", "Elevation (m)"],
                    localize=True,
                ),
            ).add_to(flood_layer)
        flood_layer.add_to(m)
        folium.map.Marker(
            location=center,
            icon=folium.DivIcon(
                html=f"""<div style="background:#0a0e14cc;color:#00d4a0;
                    font-family:monospace;font-size:11px;padding:5px 10px;
                    border:1px solid #00d4a040;border-radius:4px;white-space:nowrap;">
                    ⚠ Flood threshold &lt; {thresh:.1f} m</div>""",
                icon_size=(220, 28), icon_anchor=(110, -8),
            ),
        ).add_to(m)

    # ── Slope ──────────────────────────────────────────────────────
    if "slope" in layers and "slope_zones" in STATE["ctx"]:
        slope_gdf   = STATE["ctx"]["slope_zones"]
        slope_layer = folium.FeatureGroup(name="Terrain Slope", show=False)
        for _, row in slope_gdf.iterrows():
            s     = float(row["slope_norm"])
            red   = int(255 * s)
            green = int(200 * (1 - s))
            color = f"#{red:02x}{green:02x}00"
            folium.GeoJson(
                {"type": "Feature", "geometry": row.geometry.__geo_interface__,
                 "properties": {"slope_norm": round(s, 3)}},
                style_function=lambda feat, c=color, a=0.35 + s * 0.35: {
                    "fillColor": c, "color": "none", "fillOpacity": a, "weight": 0,
                },
            ).add_to(slope_layer)
        slope_layer.add_to(m)

    # ── OSM water ──────────────────────────────────────────────────
    if "osm_water" in layers and "osm_features" in STATE["ctx"]:
        for key, gdf in STATE["ctx"]["osm_features"].items():
            if "water" not in key and "waterway" not in key:
                continue
            wl = folium.FeatureGroup(name=f"Water: {key}", show=True)
            for _, row in gdf.iterrows():
                if row.geometry is None: continue
                folium.GeoJson(
                    {"type": "Feature", "geometry": row.geometry.__geo_interface__,
                     "properties": {}},
                    style_function=lambda f: {
                        "fillColor": "#0074d9", "color": "#0093ff",
                        "fillOpacity": 0.55, "weight": 1.5,
                    },
                ).add_to(wl)
            wl.add_to(m)

    # ── OSM roads ──────────────────────────────────────────────────
    if "osm_roads" in layers and "osm_features" in STATE["ctx"]:
        for key, gdf in STATE["ctx"]["osm_features"].items():
            if "highway" not in key: continue
            rl = folium.FeatureGroup(name="Roads (OSM)", show=False)
            for _, row in gdf.iterrows():
                if row.geometry is None: continue
                folium.GeoJson(
                    {"type": "Feature", "geometry": row.geometry.__geo_interface__,
                     "properties": {}},
                    style_function=lambda f: {"color": "#888", "weight": 1},
                ).add_to(rl)
            rl.add_to(m)

    # ── Traffic roads (Overpass) ───────────────────────────────────
    if "traffic_roads" in layers and "traffic_roads" in STATE["ctx"]:
        roads = STATE["ctx"]["traffic_roads"]
        tl    = folium.FeatureGroup(name="Live Road Network", show=True)
        highway_colors = {
            "motorway": "#ff6b35", "trunk": "#ff9f43",
            "primary": "#feca57", "secondary": "#54a0ff",
        }
        for road in roads:
            coords = [[pt[1], pt[0]] for pt in road["coords"]]
            color  = highway_colors.get(road["highway"], "#aaa")
            if len(coords) >= 2:
                folium.PolyLine(
                    coords, color=color, weight=2, opacity=0.8,
                    tooltip=f"{road['name'] or 'Road'} [{road['highway']}] {road['maxspeed']}",
                ).add_to(tl)
        tl.add_to(m)

    # ── Weather overlay ────────────────────────────────────────────
    if "weather_overlay" in layers and "weather" in STATE["ctx"]:
        wx = STATE["ctx"]["weather"]
        alert = wx.get("rain_alert_level", "LOW")
        alert_colors = {"HIGH": "#ff4444", "MODERATE": "#f0a500", "LOW": "#2ecc71"}
        acolor = alert_colors.get(alert, "#aaa")
        max_r  = wx.get("max_rain_mm_per_h", 0)
        temp   = wx.get("current_temp_c", "?")

        # Build hourly rain bar chart as SVG in popup
        hourly = wx.get("hourly_precip", [])[:24]
        times  = wx.get("hourly_time",   [])[:24]
        if hourly:
            max_h = max(hourly) or 1
            bars  = ""
            for i, val in enumerate(hourly):
                h = max(1, int((val / max_h) * 40))
                bars += f'<rect x="{i*8}" y="{40-h}" width="6" height="{h}" fill="{acolor}" opacity="0.8"/>'
            svg = f"""<svg width="195" height="50" style="margin-top:6px">
                <text x="0" y="10" fill="#888" font-size="8">24h rainfall (mm/h)</text>
                {bars}
            </svg>"""
        else:
            svg = ""

        popup_html = f"""<div style="font-family:monospace;font-size:11px;
            color:#c8d6e5;background:#0d1117;padding:10px;min-width:200px;
            border:1px solid #1a2030;border-radius:4px;">
            <div style="color:{acolor};font-size:13px;margin-bottom:4px;">
                ☁ Weather · {alert} Rain Risk</div>
            <div>🌡 Temp: {temp}°C</div>
            <div>🌧 Max rain: {max_r:.1f} mm/h</div>
            {svg}
        </div>"""

        folium.Marker(
            location=center,
            icon=folium.DivIcon(
                html=f"""<div style="background:{acolor}22;color:{acolor};
                    border:1px solid {acolor}66;border-radius:4px;
                    padding:3px 8px;font-size:10px;font-family:monospace;
                    white-space:nowrap;">☁ {alert} RAIN · {max_r:.1f}mm/h</div>""",
                icon_size=(180, 24), icon_anchor=(90, 30),
            ),
            popup=folium.Popup(popup_html, max_width=220),
        ).add_to(m)

    # ── Disaster alerts ────────────────────────────────────────────
    if "disaster_markers" in layers and "disaster_alerts" in STATE["ctx"]:
        alerts  = STATE["ctx"]["disaster_alerts"]
        dal     = folium.FeatureGroup(name="Disaster Alerts (GDACS)", show=True)
        cluster = MarkerCluster().add_to(dal)
        sev_colors = {"Red": "#ff4444", "Orange": "#f0a500", "Green": "#2ecc71"}
        for a in alerts:
            if a.get("lat") is None: continue
            color = sev_colors.get(a.get("severity", ""), "#00d4a0")
            folium.CircleMarker(
                location=[a["lat"], a["lon"]],
                radius=12,
                color=color, fill=True, fill_color=color, fill_opacity=0.6,
                tooltip=f"{a['type']}: {a['title'][:60]}",
                popup=folium.Popup(
                    f"<div style='font-family:monospace;font-size:11px'>"
                    f"<b style='color:{color}'>{a['type']} ({a['severity']})</b><br>"
                    f"{a['title']}<br><small>{a['date']}</small></div>",
                    max_width=280,
                ),
            ).add_to(cluster)
        dal.add_to(m)

    # ── Air quality markers ────────────────────────────────────────
    if "air_quality_markers" in layers and "air_quality" in STATE["ctx"]:
        stations = STATE["ctx"]["air_quality"].get("stations", [])
        aql      = folium.FeatureGroup(name="Air Quality Stations (OpenAQ)", show=True)
        for st in stations:
            if st.get("lat") is None: continue
            folium.CircleMarker(
                location=[st["lat"], st["lon"]],
                radius=8,
                color="#00d4a0", fill=True, fill_color="#00d4a0", fill_opacity=0.7,
                tooltip=st["name"],
                popup=folium.Popup(
                    f"<div style='font-family:monospace;font-size:11px'>"
                    f"<b style='color:#00d4a0'>{st['name']}</b><br>"
                    f"Sensors: {', '.join(st['sensors'])}<br>"
                    f"Last update: {st['last_updated']}</div>",
                    max_width=240,
                ),
            ).add_to(aql)
        aql.add_to(m)

    # ── Legend ─────────────────────────────────────────────────────
    place    = STATE["ctx"].get("geocode", {}).get("place", "")
    elev_min = STATE["ctx"].get("elevation", {}).get("min", None)
    elev_max = STATE["ctx"].get("elevation", {}).get("max", None)
    wx       = STATE["ctx"].get("weather", {})
    alerts   = STATE["ctx"].get("disaster_alerts", [])

    elev_range = f"Elevation: {elev_min:.0f}m – {elev_max:.0f}m<br>" if (
        isinstance(elev_min, float) and isinstance(elev_max, float)) else ""
    wx_line = (f"Rain: {wx.get('rain_alert_level','?')} · {wx.get('max_rain_mm_per_h',0):.1f}mm/h<br>"
               if wx else "")
    alert_line = f"Alerts: {len(alerts)} disaster events<br>" if alerts else ""

    legend = f"""
    <div style="position:fixed;bottom:24px;left:16px;z-index:1000;
         background:#0a0e14ee;padding:14px 18px;border:1px solid #00d4a030;
         border-radius:6px;font-family:'Courier New',monospace;font-size:11px;
         color:#c8d6e5;min-width:210px;backdrop-filter:blur(6px);">
      <div style="color:#00d4a0;font-size:13px;font-weight:bold;
           margin-bottom:10px;letter-spacing:1px;">{title}</div>
      <div style="color:#4a5568;margin-bottom:8px;font-size:10px;">📍 {place}</div>
      {"<div><span style='color:#d32'>■</span> High flood risk</div>" if "flood_zones" in layers else ""}
      {"<div><span style='color:#f73'>■</span> Medium flood risk</div>" if "flood_zones" in layers else ""}
      {"<div><span style='color:#0af'>■</span> Water bodies</div>" if "osm_water" in layers else ""}
      {"<div><span style='color:#ff4'>■</span> Steep slope</div>" if "slope" in layers else ""}
      {"<div><span style='color:#f44'>⚠</span> Disaster alerts</div>" if "disaster_markers" in layers else ""}
      {"<div><span style='color:#0d4'>●</span> AQ stations</div>" if "air_quality_markers" in layers else ""}
      <div style="margin-top:8px;color:#4a5568;font-size:10px;border-top:1px solid #1a2030;padding-top:8px;">
        {elev_range}{wx_line}{alert_line}
        DEM: SRTM 30m · OSM · Open-Meteo · GDACS<br>
        <span style="color:#00d4a040;">GeoAI Agent v2.0</span>
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))
    Fullscreen().add_to(m)
    MiniMap(toggle_display=True).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    m.save(CFG["MAP_PATH"])
    STATE["map_ready"]    = True
    STATE["active_layers"] = layers
    sio.emit("map_ready", {"path": "/static/map_output.html", "type": "2d"})
    log("success", "render_map",
        f"Map saved → {CFG['MAP_PATH']} | {len(layers)} layers",
        {"layers": layers})
    return {"status": "rendered", "path": CFG["MAP_PATH"], "layers": layers}


@tool(
    name        = "render_3d_terrain",
    description = "Generate an interactive 3D terrain visualization using deck.gl with SRTM elevation data. Use when user asks for 3D, terrain view, or elevation visualization.",
    params      = {
        "title"         : "string — map title",
        "show_flood"    : "bool — overlay flood zones as colored markers",
        "show_weather"  : "bool — show weather data panel",
    }
)
def render_3d_terrain(title: str = "3D Terrain", show_flood: bool = True, show_weather: bool = True) -> Dict:
    geo = STATE["ctx"].get("geocode", {})
    if not geo:
        raise ValueError("Call geocode_place first.")

    center   = geo.get("center", [13.6288, 79.4192])
    bbox     = geo.get("bbox", {})
    elev_ctx = STATE["ctx"].get("elevation", {})
    flood_gdf = STATE["ctx"].get("flood_zones", None)
    wx        = STATE["ctx"].get("weather", {})

    log("info", "render_3d_terrain", f"Building deck.gl 3D terrain...")

    # Build flood data for JS
    flood_js = "[]"
    if show_flood and flood_gdf is not None:
        pts = []
        for _, row in flood_gdf.iterrows():
            centroid = row.geometry.centroid
            pts.append({
                "lat"    : centroid.y,
                "lon"    : centroid.x,
                "risk"   : round(float(row["risk"]), 3),
                "elev"   : round(float(row["elevation_m"]), 1),
            })
        flood_js = json.dumps(pts)

    # Weather panel data
    wx_html = ""
    if show_weather and wx:
        alert = wx.get("rain_alert_level", "LOW")
        acolor = {"HIGH": "#ff4444", "MODERATE": "#f0a500", "LOW": "#2ecc71"}.get(alert, "#aaa")
        temp  = wx.get("current_temp_c", "?")
        maxr  = wx.get("max_rain_mm_per_h", 0)
        # Mini sparkline for precip
        hourly = wx.get("hourly_precip", [])[:24]
        mx     = max(hourly) if hourly else 1
        spark  = ""
        for i, v in enumerate(hourly):
            h = max(1, int((v / mx) * 28)) if mx else 1
            spark += f'<rect x="{i*5}" y="{28-h}" width="4" height="{h}" fill="{acolor}" opacity="0.85"/>'

        wx_html = f"""
        <div id="wx-panel" style="position:absolute;top:16px;right:16px;z-index:10;
            background:#0a0e14dd;border:1px solid #1a2030;border-radius:6px;
            padding:12px 16px;font-family:'Courier New',monospace;font-size:11px;
            color:#c8d6e5;min-width:190px;backdrop-filter:blur(8px);">
            <div style="color:{acolor};font-size:12px;margin-bottom:6px;letter-spacing:1px;">
                ☁ Weather · {alert}</div>
            <div>🌡 {temp}°C &nbsp; 🌧 {maxr:.1f} mm/h</div>
            <svg width="120" height="32" style="margin-top:6px;display:block">
                {spark}
            </svg>
            <div style="color:#4a5568;font-size:9px;margin-top:4px;">24h rainfall forecast</div>
        </div>"""

    # Elevation stats
    elev_min  = elev_ctx.get("min",  0)
    elev_max  = elev_ctx.get("max",  0)
    elev_mean = elev_ctx.get("mean", 0)

    # disaster alerts
    alerts   = STATE["ctx"].get("disaster_alerts", [])
    alert_js = json.dumps([
        {"lat": a["lat"], "lon": a["lon"],
         "title": a["title"][:60], "type": a.get("type", ""),
         "severity": a.get("severity", "")}
        for a in alerts if a.get("lat") is not None
    ])

    place = geo.get("place", "")
    lon_center = center[1]
    lat_center = center[0]

    html_3d = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<script src="https://unpkg.com/deck.gl@latest/dist.min.js"></script>
<script src="https://unpkg.com/maplibre-gl@3/dist/maplibre-gl.js"></script>
<link  href="https://unpkg.com/maplibre-gl@3/dist/maplibre-gl.css" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#06090e;overflow:hidden;font-family:'Courier New',monospace}}
#map{{width:100vw;height:100vh}}
#legend{{
    position:absolute;bottom:20px;left:16px;z-index:10;
    background:#0a0e14dd;border:1px solid #00d4a030;border-radius:6px;
    padding:12px 16px;font-size:11px;color:#c8d6e5;min-width:200px;
    backdrop-filter:blur(8px);
}}
#legend .title{{color:#00d4a0;font-size:13px;font-weight:bold;
    letter-spacing:1px;margin-bottom:8px;}}
#legend .sub{{color:#4a5568;font-size:9px;margin-top:6px;
    border-top:1px solid #1a2030;padding-top:6px;}}
#tooltip{{
    position:absolute;pointer-events:none;z-index:20;
    background:#0a0e14ee;border:1px solid #00d4a030;
    border-radius:4px;padding:8px 12px;font-size:11px;color:#c8d6e5;
    display:none;backdrop-filter:blur(6px);
}}
#controls{{
    position:absolute;top:16px;left:16px;z-index:10;display:flex;gap:6px;
}}
.ctrl-btn{{
    background:#0a0e14dd;border:1px solid #1a2030;color:#c8d6e5;
    font-family:'Courier New',monospace;font-size:10px;padding:5px 10px;
    border-radius:3px;cursor:pointer;letter-spacing:1px;
    backdrop-filter:blur(6px);transition:all .2s;
}}
.ctrl-btn:hover{{border-color:#00d4a040;color:#00d4a0;background:#00d4a010;}}
.ctrl-btn.active{{border-color:#00d4a0;color:#00d4a0;background:#00d4a015;}}
</style>
</head>
<body>
<div id="map"></div>
<div id="tooltip"></div>
{wx_html}
<div id="controls">
    <button class="ctrl-btn active" id="btn-terrain" onclick="toggleLayer('terrain')">⛰ TERRAIN</button>
    <button class="ctrl-btn active" id="btn-flood"   onclick="toggleLayer('flood')">⚠ FLOOD</button>
    <button class="ctrl-btn"        id="btn-alerts"  onclick="toggleLayer('alerts')">🔴 ALERTS</button>
</div>
<div id="legend">
    <div class="title">⛰ {title}</div>
    <div style="color:#4a5568;font-size:10px;margin-bottom:6px;">📍 {place}</div>
    <div><span style="color:#ff4136">■</span> High elevation</div>
    <div><span style="color:#2ecc71">■</span> Mid elevation</div>
    <div><span style="color:#001f3f">■</span> Low elevation</div>
    <div><span style="color:#d32a2a">●</span> Flood risk zones</div>
    <div class="sub">
        Elev: {elev_min:.0f}m – {elev_max:.0f}m (mean {elev_mean:.0f}m)<br>
        DEM: SRTM 30m · deck.gl TerrainLayer<br>
        <span style="color:#00d4a040">GeoAI v2.0 · 3D View</span>
    </div>
</div>

<script>
const {{DeckGL, TerrainLayer, ScatterplotLayer, TextLayer}} = deck;

const FLOOD_DATA  = {flood_js};
const ALERT_DATA  = {alert_js};
const CENTER_LON  = {lon_center};
const CENTER_LAT  = {lat_center};

let layerVisibility = {{terrain: true, flood: true, alerts: false}};

const TERRAIN_IMAGE = `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{{z}}/{{x}}/{{y}}.png`;
const SURFACE_IMAGE = `https://basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}@2x.png`;

function buildLayers() {{
    const layers = [];

    if (layerVisibility.terrain) {{
        layers.push(new TerrainLayer({{
            id: 'terrain',
            elevationDecoder: {{
                rScaler: 256,
                gScaler: 1,
                bScaler: 1/256,
                offset: -32768,
            }},
            elevationData: TERRAIN_IMAGE,
            texture       : SURFACE_IMAGE,
            wireframe     : false,
            color         : [255, 255, 255],
            operation     : 'terrain+draw',
        }}));
    }}

    if (layerVisibility.flood && FLOOD_DATA.length > 0) {{
        layers.push(new ScatterplotLayer({{
            id: 'flood',
            data: FLOOD_DATA,
            getPosition: d => [d.lon, d.lat, (d.elev || 0) + 80],
            getRadius  : 180,
            getFillColor: d => {{
                const r = d.risk;
                return [80 + r*175, 42, Math.max(0, 80 - r*60), 200];
            }},
            pickable: true,
            onHover: ({{object, x, y}}) => {{
                const tip = document.getElementById('tooltip');
                if (object) {{
                    tip.style.display = 'block';
                    tip.style.left    = (x+12)+'px';
                    tip.style.top     = (y-10)+'px';
                    tip.innerHTML = `⚠ Flood Risk: ${{(object.risk*100).toFixed(0)}}%<br>Elevation: ${{object.elev}}m`;
                }} else {{
                    tip.style.display = 'none';
                }}
            }},
        }}));
    }}

    if (layerVisibility.alerts && ALERT_DATA.length > 0) {{
        layers.push(new ScatterplotLayer({{
            id: 'alerts',
            data: ALERT_DATA,
            getPosition: d => [d.lon, d.lat, 1000],
            getRadius  : 500,
            getFillColor: [255, 68, 68, 210],
            pickable: true,
            onHover: ({{object, x, y}}) => {{
                const tip = document.getElementById('tooltip');
                if (object) {{
                    tip.style.display = 'block';
                    tip.style.left    = (x+12)+'px';
                    tip.style.top     = (y-10)+'px';
                    tip.innerHTML = `🔴 ${{object.type}}<br>${{object.title}}`;
                }} else {{
                    tip.style.display = 'none';
                }}
            }},
        }}));
    }}

    return layers;
}}

const deckgl = new DeckGL({{
    container : 'map',
    mapStyle  : 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    initialViewState: {{
        longitude: CENTER_LON,
        latitude : CENTER_LAT,
        zoom     : 11,
        pitch    : 52,
        bearing  : -18,
    }},
    controller: true,
    layers    : buildLayers(),
}});

function toggleLayer(name) {{
    layerVisibility[name] = !layerVisibility[name];
    const btn = document.getElementById('btn-'+name);
    btn.classList.toggle('active', layerVisibility[name]);
    deckgl.setProps({{layers: buildLayers()}});
}}
</script>
</body>
</html>"""

    with open(CFG["MAP_3D_PATH"], "w") as f:
        f.write(html_3d)

    STATE["map_3d_ready"] = True
    sio.emit("map_ready", {"path": "/static/map_3d.html", "type": "3d"})
    log("success", "render_3d_terrain",
        f"3D terrain saved → {CFG['MAP_3D_PATH']}")
    return {"status": "rendered_3d", "path": CFG["MAP_3D_PATH"]}

# 07 | LLM CORE — CONVERSATIONAL INTENT PARSER
SYSTEM_PROMPT_TEMPLATE = """You are GeoAgent, a conversational geospatial intelligence system.
You maintain context across multiple user turns and execute GIS tools step by step.

SESSION MEMORY (from previous turns):
{memory}

Each response must be ONLY a single JSON object — no markdown, no prose:
{{
  "tool"       : "<tool_name>",
  "params"     : {{ ... }},
  "reasoning"  : "<one short sentence>",
  "user_reply" : "<friendly one-line message to show the user in chat>",
  "suggestions": ["<follow-up question 1>", "<follow-up question 2>"]
}}

Or when complete:
{{
  "tool"       : "DONE",
  "params"     : {{}},
  "reasoning"  : "Analysis complete.",
  "user_reply" : "<summary of what was done and what the map shows>",
  "suggestions": ["<3 smart follow-up questions based on what was just analyzed>"]
}}

AVAILABLE TOOLS:
{tools}

TOOL SELECTION RULES:
1. geocode_place is ALWAYS first.
2. fetch_elevation_grid must come before analyze_flood_prone, compute_slope, or render_3d_terrain.
3. render_map or render_3d_terrain is ALWAYS last.
4. If user mentions "3D" or "terrain view" or "elevation model": use render_3d_terrain.
5. If user mentions "weather" or "rain" or "rainfall": include fetch_weather_realtime.
6. If user mentions "disaster" or "alert" or "emergency": include fetch_disaster_alerts.
7. If user mentions "air" or "pollution" or "AQ": include fetch_air_quality.
8. If user mentions "traffic" or "roads" or "transport": include fetch_live_traffic.
9. If user mentions "flood": geocode → fetch_elevation_grid → analyze_flood_prone → render_map(layers=[flood_zones,elevation_heatmap]).
10. For combined queries, chain all relevant tools before rendering.
11. layers param in render_map must be a JSON array. Include all fetched data layers.
12. Use session memory: if user says "same place" or "also show me", reuse last_place.
"""

INTENT_CLASSIFIER_PROMPT = """You are a geospatial query intent parser.
Given a user message, extract the intent as JSON:
{{
  "place"          : "<place name or null if using previous>",
  "analyses"       : ["flood", "elevation", "slope", "weather", "disaster", "air_quality", "traffic", "3d"],
  "view_type"      : "2d" or "3d",
  "is_followup"    : true/false,
  "rephrased_query": "<clear restatement of what user wants>"
}}

Session memory: {memory}
User message: "{query}"

Return ONLY the JSON object.
"""

def build_system_prompt() -> str:
    mem = json.dumps(STATE["session_memory"], default=str)
    return SYSTEM_PROMPT_TEMPLATE.format(tools=tools_schema_str(), memory=mem)

def parse_intent(query: str) -> Dict:
    """Use LLM to parse intent from conversational query."""
    mem = json.dumps(STATE["session_memory"], default=str)
    prompt = INTENT_CLASSIFIER_PROMPT.format(memory=mem, query=query)
    try:
        resp = requests.post(
            CFG["OLLAMA_CHAT_URL"],
            json={
                "model"  : CFG["OLLAMA_MODEL"],
                "messages": [{"role": "user", "content": prompt}],
                "stream" : False,
                "options": {"temperature": 0.0, "num_predict": 300},
            },
            timeout=30,
        )
        raw    = resp.json()["message"]["content"]
        intent = extract_json(raw)
        return intent or {}
    except Exception:
        return {}

def call_ollama(messages: List[Dict]) -> str:
    try:
        resp = requests.post(
            CFG["OLLAMA_CHAT_URL"],
            json={
                "model"   : CFG["OLLAMA_MODEL"],
                "messages": messages,
                "stream"  : False,
                "options" : {
                    "temperature": CFG["LLM_TEMPERATURE"],
                    "num_predict": CFG["LLM_MAX_TOKENS"],
                    "stop"       : ["\n\n\n"],
                },
            },
            timeout=90,
        )
        return resp.json()["message"]["content"]
    except Exception as e:
        log("error", "llm", f"Ollama call failed: {e}")
        raise

def extract_json(raw: str) -> Optional[Dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(raw[start:end])
    except json.JSONDecodeError:
        return None

# 08 | AGENT LOOP
def generate_suggestions(analyses: List[str], place: str) -> List[str]:
    """Generate smart follow-up suggestions based on what was analyzed."""
    suggestions = []
    if "flood" in analyses:
        suggestions.append(f"Show weather and rainfall forecast for {place}")
        suggestions.append(f"Show disaster alerts near {place}")
    if "elevation" in analyses and "3d" not in analyses:
        suggestions.append(f"Show 3D terrain view of {place}")
    if "weather" not in analyses:
        suggestions.append(f"What is the current weather near {place}?")
    if "air_quality" not in analyses:
        suggestions.append(f"Check air quality near {place}")
    if "traffic" not in analyses:
        suggestions.append(f"Show road network near {place}")
    return suggestions[:4]

def run_agent(query: str):
    STATE.update({
        "running"  : True,
        "map_ready": False, "map_3d_ready": False,
        "query"    : query,
        "steps"    : [],
        "ctx"      : {},
        "active_layers": [],
    })

    # Preserve session memory across runs
    log("system", "agent", f"Query: {query}")

    # Step 1: parse intent
    intent = parse_intent(query)
    log("info", "agent", f"Intent: {json.dumps(intent, default=str)[:200]}")

    # Show intent echo in chat
    place = intent.get("place") or STATE["session_memory"].get("last_place", "")
    analyses = intent.get("analyses", [])
    view_type = intent.get("view_type", "2d")
    rephrased = intent.get("rephrased_query", query)

    chat_push("agent", f"Understood: {rephrased}", {
        "intent": intent,
        "type"  : "intent_echo",
    })

    # Emit suggestions immediately
    if intent.get("is_followup") and STATE["session_memory"].get("last_place"):
        sio.emit("suggestions", generate_suggestions(analyses, place))

    messages: List[Dict] = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user",   "content": f'Geospatial query: "{query}"\nParsed intent: {json.dumps(intent)}\n\nGive me the FIRST tool call as JSON:'},
    ]

    steps_done = 0

    try:
        while steps_done < CFG["MAX_AGENT_STEPS"]:
            steps_done += 1
            log("info", "llm", f"Requesting step {steps_done}…")
            raw  = call_ollama(messages)
            log("debug", "llm", raw[:120] + ("…" if len(raw) > 120 else ""))
            call = extract_json(raw)

            if call is None:
                log("warning", "agent", "JSON parse failed — retrying")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user",
                                 "content": "Return ONLY a valid JSON object with tool, params, reasoning, user_reply, suggestions."})
                continue

            tool_name = call.get("tool", "")
            params    = call.get("params", {})
            reason    = call.get("reasoning", "")
            user_reply = call.get("user_reply", "")
            suggestions = call.get("suggestions", [])

            log("info", "agent", f"→ {tool_name}  |  {reason}")

            if user_reply:
                chat_push("agent", user_reply, {"tool": tool_name, "type": "step"})

            if tool_name == "DONE":
                log("success", "agent", "Agent declared task complete.")
                if suggestions:
                    sio.emit("suggestions", suggestions)
                break

            if tool_name not in TOOL_REGISTRY:
                log("error", "agent", f"Unknown tool: {tool_name}")
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user",
                                 "content": f'Tool "{tool_name}" does not exist. Use only listed tools.'})
                continue

            try:
                if tool_name in ("render_map",) and isinstance(params.get("layers"), str):
                    params["layers"] = json.loads(params["layers"])
                if isinstance(params.get("show_flood"), str):
                    params["show_flood"] = params["show_flood"].lower() == "true"
                if isinstance(params.get("show_weather"), str):
                    params["show_weather"] = params["show_weather"].lower() == "true"

                result     = TOOL_REGISTRY[tool_name]["fn"](**params)
                result_str = json.dumps(result, default=str)[:600]

                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user",
                                 "content": f"Tool result: {result_str}\n\nNext tool call:"})

                if tool_name in ("render_map", "render_3d_terrain"):
                    # Final suggestions
                    final_suggs = generate_suggestions(analyses, place)
                    if suggestions:
                        final_suggs = suggestions[:4]
                    sio.emit("suggestions", final_suggs)
                    break

            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                log("error", tool_name, err)
                if tool_name in ("render_map", "render_3d_terrain"):
                    log("warning", "agent", "Render failed — triggering fallback")
                    break
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user",
                                 "content": f"Tool execution failed: {err}. Adjust params or try next step."})

        # Safety fallback
        if not STATE["map_ready"] and not STATE["map_3d_ready"]:
            log("warning", "agent", "Map not rendered — forcing render_map")
            available = []
            if "flood_zones"  in STATE["ctx"]: available.append("flood_zones")
            if "elevation"    in STATE["ctx"]: available.append("elevation_heatmap")
            if "slope_zones"  in STATE["ctx"]: available.append("slope")
            if "weather"      in STATE["ctx"]: available.append("weather_overlay")
            if "disaster_alerts" in STATE["ctx"]: available.append("disaster_markers")
            if "air_quality"  in STATE["ctx"]: available.append("air_quality_markers")
            if "traffic_roads" in STATE["ctx"]: available.append("traffic_roads")
            render_map(title=f"GeoAI: {query[:50]}", layers=available or ["elevation_heatmap"])

    except Exception:
        tb = traceback.format_exc()
        log("error", "agent", f"Fatal exception:\n{tb}")
        sio.emit("agent_error", {"error": tb})
        chat_push("agent", "An error occurred. Please try again.", {"type": "error"})

    finally:
        STATE["running"] = False
        sio.emit("agent_done", {"steps": steps_done, "map_ready": STATE["map_ready"] or STATE["map_3d_ready"]})
        log("system", "agent", f"Session ended — {steps_done} steps")

# 09 | FLASK ROUTES
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/query", methods=["POST"])
def api_query():
    if STATE["running"]:
        return jsonify({"error": "Agent already running"}), 409
    body  = request.get_json(force=True)
    query = (body or {}).get("query", "").strip()
    if not query:
        return jsonify({"error": "Empty query"}), 400
    thread = threading.Thread(target=run_agent, args=(query,), daemon=True)
    thread.start()
    return jsonify({"status": "started", "query": query})

@app.route("/api/status")
def api_status():
    return jsonify({
        "running"      : STATE["running"],
        "map_ready"    : STATE["map_ready"],
        "map_3d_ready" : STATE["map_3d_ready"],
        "steps"        : len(STATE["steps"]),
        "model"        : CFG["OLLAMA_MODEL"],
        "session_memory": STATE["session_memory"],
        "active_layers": STATE["active_layers"],
    })

@app.route("/api/tools")
def api_tools():
    return jsonify({
        name: {"description": t["description"], "params": t["params"]}
        for name, t in TOOL_REGISTRY.items()
    })

@app.route("/api/config", methods=["POST"])
def api_config():
    body = request.get_json(force=True) or {}
    if "model"    in body: CFG["OLLAMA_MODEL"]   = body["model"]
    if "grid_res" in body: CFG["ELEV_GRID_RES"]  = int(body["grid_res"])
    return jsonify({"config": {k: CFG[k] for k in ("OLLAMA_MODEL", "ELEV_GRID_RES")}})

@app.route("/api/clear_memory", methods=["POST"])
def api_clear_memory():
    STATE["session_memory"] = {}
    STATE["conversation"]   = []
    return jsonify({"status": "cleared"})

@sio.on("connect")
def on_connect():
    emit("connected", {
        "model"  : CFG["OLLAMA_MODEL"],
        "tools"  : list(TOOL_REGISTRY.keys()),
        "history": STATE["conversation"][-20:],
    })
    if STATE["conversation"]:
        emit("restore_chat", {"messages": STATE["conversation"][-20:]})

# 10 | HTML TEMPLATE — CONVERSATIONAL UI
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>GeoAI Agent v2</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;600;700&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{
  --teal:#00d4a0;--teal2:#00b88a;--teal-glow:#00d4a015;--teal-dim:#00d4a035;
  --bg:#060a10;--surface:#0b1018;--surface2:#0f1520;--surface3:#131c28;
  --border:#1c2535;--border2:#243044;
  --text:#bfcfdf;--dim:#3d5068;--bright:#e8f0f8;
  --red:#ef4444;--amber:#f59e0b;--green:#10b981;--blue:#3b82f6;
  --user-bg:#0f2040;--agent-bg:#0b1520;
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden;background:var(--bg)}
body{
  display:grid;
  grid-template-rows:48px 1fr;
  grid-template-columns:400px 1fr;
  grid-template-areas:"hdr hdr" "chat map";
  font-family:'JetBrains Mono',monospace;
  color:var(--text);
}

/* ── Header ─────────────────────────────────────────────────────── */
header{
  grid-area:hdr;
  background:var(--surface);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 18px;gap:12px;
}
.logo{
  font-family:'Space Grotesk',sans-serif;
  font-weight:700;font-size:17px;letter-spacing:3px;
  color:var(--teal);text-shadow:0 0 20px var(--teal-dim);
}
.badge{
  font-size:9px;color:var(--dim);border:1px solid var(--border);
  padding:2px 7px;border-radius:2px;letter-spacing:1px;text-transform:uppercase;
}
.badge.live{color:var(--teal);border-color:var(--teal-dim);}
#hdr-right{margin-left:auto;display:flex;align-items:center;gap:10px;}
.pulse{width:6px;height:6px;border-radius:50%;background:var(--dim);flex-shrink:0;}
.pulse.on{background:var(--teal);box-shadow:0 0 8px var(--teal);animation:blink 1.2s infinite;}
.pulse.err{background:var(--red);}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}

/* ── Chat Panel ──────────────────────────────────────────────────── */
.chat-panel{
  grid-area:chat;
  background:var(--surface);
  border-right:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden;
}

/* Quick examples bar */
.examples-bar{
  padding:10px 14px 0;
  border-bottom:1px solid var(--border);
  background:var(--surface2);
}
.examples-label{font-size:9px;color:var(--dim);letter-spacing:2px;
  text-transform:uppercase;margin-bottom:8px;}
.ex-chips{display:flex;flex-wrap:wrap;gap:5px;padding-bottom:10px;}
.ex-chip{
  font-size:9px;padding:4px 9px;border-radius:12px;cursor:pointer;
  border:1px solid var(--border);color:var(--dim);background:none;
  font-family:'JetBrains Mono',monospace;letter-spacing:.3px;
  transition:all .15s;white-space:nowrap;line-height:1.3;
}
.ex-chip:hover{color:var(--teal);border-color:var(--teal-dim);background:var(--teal-glow);}
.ex-chip.weather{color:#60a5fa;border-color:#1d4ed840;}
.ex-chip.disaster{color:#f87171;border-color:#7f1d1d40;}
.ex-chip.air{color:#a78bfa;border-color:#4c1d9540;}
.ex-chip.traffic{color:#fbbf24;border-color:#78350f40;}
.ex-chip.terrain{color:#34d399;border-color:#064e3b40;}

/* Chat messages */
.chat-messages{
  flex:1;overflow-y:auto;padding:14px;
  display:flex;flex-direction:column;gap:10px;
}
.chat-messages::-webkit-scrollbar{width:3px;}
.chat-messages::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px;}

.msg{display:flex;gap:9px;align-items:flex-start;animation:msgIn .2s ease;}
@keyframes msgIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.msg.user{flex-direction:row-reverse;}

.avatar{
  width:26px;height:26px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:bold;
}
.avatar.agent{background:var(--teal-glow);border:1px solid var(--teal-dim);color:var(--teal);}
.avatar.user {background:#1e3a5f;border:1px solid #2d5a8e40;color:#60a5fa;}

.bubble{
  max-width:290px;padding:9px 13px;border-radius:10px;
  font-size:11px;line-height:1.6;
}
.msg.agent .bubble{
  background:var(--agent-bg);border:1px solid var(--border);
  border-top-left-radius:2px;color:var(--text);
}
.msg.user .bubble{
  background:var(--user-bg);border:1px solid #2d5a8e40;
  border-top-right-radius:2px;color:#93c5fd;text-align:right;
}
.bubble .intent-tag{
  display:inline-block;font-size:9px;background:var(--teal-glow);
  color:var(--teal);padding:1px 6px;border-radius:2px;
  margin-bottom:4px;letter-spacing:.5px;
}
.bubble .tool-tag{
  display:inline-block;font-size:9px;background:#1a2030;
  color:var(--dim);padding:1px 6px;border-radius:2px;
  margin-bottom:3px;letter-spacing:.3px;
}
.msg-time{font-size:8px;color:var(--dim);margin-top:3px;
  text-align:right;padding:0 2px;}

/* Typing indicator */
.typing{display:flex;gap:4px;align-items:center;padding:4px 2px;}
.typing span{
  width:5px;height:5px;border-radius:50%;background:var(--teal-dim);
  animation:dot 1.2s infinite;
}
.typing span:nth-child(2){animation-delay:.2s;}
.typing span:nth-child(3){animation-delay:.4s;}
@keyframes dot{0%,60%,100%{opacity:.3;transform:scale(1)}30%{opacity:1;transform:scale(1.3)}}

/* Suggestion chips */
.suggestions{
  padding:8px 14px;border-top:1px solid var(--border);
  background:var(--surface2);
}
.sugg-label{font-size:9px;color:var(--dim);letter-spacing:1.5px;
  text-transform:uppercase;margin-bottom:7px;}
.sugg-chips{display:flex;flex-direction:column;gap:4px;}
.sugg-chip{
  font-size:10px;padding:5px 10px;border-radius:4px;cursor:pointer;
  border:1px solid var(--border2);color:var(--dim);background:none;
  font-family:'JetBrains Mono',monospace;text-align:left;
  transition:all .15s;letter-spacing:.2px;line-height:1.4;
}
.sugg-chip:hover{color:var(--bright);border-color:var(--border2);
  background:var(--surface3);transform:translateX(2px);}
.sugg-chip::before{content:"→ ";color:var(--teal);opacity:.6;}

/* Input area */
.input-area{
  padding:12px 14px;border-top:1px solid var(--border);
  background:var(--surface2);
}
.input-row{display:flex;gap:8px;align-items:flex-end;}
textarea{
  flex:1;resize:none;background:var(--bg);
  border:1px solid var(--border);color:var(--bright);
  font-family:'JetBrains Mono',monospace;font-size:11px;
  padding:9px 11px;border-radius:6px;outline:none;line-height:1.5;
  min-height:40px;max-height:100px;height:40px;
  transition:border-color .2s, height .1s;
  overflow-y:hidden;
}
textarea:focus{border-color:var(--teal-dim);}
.send-btn{
  width:36px;height:36px;background:var(--teal);border:none;
  border-radius:6px;cursor:pointer;display:flex;align-items:center;
  justify-content:center;flex-shrink:0;transition:opacity .2s,transform .1s;
  font-size:14px;
}
.send-btn:hover:not(:disabled){opacity:.85;transform:translateY(-1px);}
.send-btn:disabled{opacity:.2;cursor:not-allowed;}

/* Tool pipeline strip */
.pipeline-strip{
  padding:8px 14px;border-top:1px solid var(--border);
  background:var(--surface);display:flex;gap:4px;flex-wrap:wrap;
}
.pip-chip{
  font-size:8px;padding:2px 7px;border-radius:2px;
  border:1px solid var(--border);color:var(--dim);
  letter-spacing:.5px;transition:all .2s;
}
.pip-chip.active {color:var(--teal);border-color:var(--teal-dim);background:var(--teal-glow);}
.pip-chip.done   {color:var(--green);border-color:#10b98130;background:#10b98110;}
.pip-chip.err    {color:var(--red);border-color:#ef444430;background:#ef44440a;}

/* Config row */
.cfg-row{
  padding:8px 14px;border-top:1px solid var(--border);
  background:var(--surface);display:flex;gap:6px;align-items:center;
}
select{
  flex:1;background:var(--bg);border:1px solid var(--border);
  color:var(--text);font-family:'JetBrains Mono',monospace;
  font-size:10px;padding:4px 7px;border-radius:3px;outline:none;
}
.apply-btn,.clear-btn{
  font-family:'JetBrains Mono',monospace;font-size:9px;
  color:var(--dim);background:none;border:1px solid var(--border);
  padding:4px 8px;border-radius:3px;cursor:pointer;letter-spacing:1px;
  transition:all .2s;white-space:nowrap;
}
.apply-btn:hover{color:var(--teal);border-color:var(--teal-dim);background:var(--teal-glow);}
.clear-btn:hover{color:var(--red);border-color:#ef444440;background:#ef44440a;}

/* ── Map Area ────────────────────────────────────────────────────── */
.map-area{
  grid-area:map;position:relative;background:#04070c;
  display:flex;align-items:center;justify-content:center;
}
.map-placeholder{
  text-align:center;color:var(--dim);font-size:11px;line-height:2.6;
  user-select:none;
}
.map-placeholder .icon{font-size:56px;display:block;margin-bottom:18px;opacity:.25;}
#map-frame{width:100%;height:100%;border:none;display:none;}

/* View switcher */
.view-switch{
  position:absolute;top:14px;right:14px;z-index:10;
  display:none;gap:4px;
}
.vbtn{
  background:#0a0e14cc;border:1px solid var(--border);
  color:var(--dim);font-family:'JetBrains Mono',monospace;
  font-size:9px;padding:5px 10px;border-radius:3px;cursor:pointer;
  letter-spacing:1px;backdrop-filter:blur(6px);transition:all .2s;
}
.vbtn:hover,.vbtn.active{color:var(--teal);border-color:var(--teal-dim);background:#00d4a012;}

/* Progress bar */
.progress{position:absolute;bottom:0;left:0;right:0;height:2px;background:var(--border);}
.progress-fill{
  height:100%;background:linear-gradient(90deg,var(--teal),var(--blue));
  width:0%;transition:width .6s ease;box-shadow:0 0 12px var(--teal);
}

/* Status overlay */
#status-chip{
  position:absolute;top:14px;left:14px;z-index:10;
  background:#0a0e14cc;border:1px solid var(--border);
  padding:4px 10px;font-size:9px;color:var(--dim);
  border-radius:3px;backdrop-filter:blur(6px);display:none;
  letter-spacing:1px;
}
</style>
</head>
<body>

<header>
  <div class="logo">GEO·AI</div>
  <div class="badge live">LIVE DATA</div>
  <div class="badge live">OPEN-METEO</div>
  <div class="badge live">GDACS</div>
  <div class="badge live">OpenAQ</div>
  <div class="badge">SRTM 30m</div>
  <div id="hdr-right">
    <div class="badge" id="hdr-model">MISTRAL · LOCAL</div>
    <div class="pulse" id="pulse"></div>
  </div>
</header>

<!-- ═══ CHAT PANEL ═══ -->
<div class="chat-panel">

  <div class="examples-bar">
    <div class="examples-label">Quick Queries</div>
    <div class="ex-chips">
      <button class="ex-chip terrain" onclick="sendQuery('Show 3D terrain and flood risk near Tirupati')">⛰ 3D terrain + flood — Tirupati</button>
      <button class="ex-chip weather" onclick="sendQuery('Weather and rainfall forecast near Vijayawada')">🌧 Rainfall forecast — Vijayawada</button>
      <button class="ex-chip disaster" onclick="sendQuery('Show disaster alerts and flood zones near Nellore')">🔴 Disaster alerts — Nellore</button>
      <button class="ex-chip air" onclick="sendQuery('Air quality and elevation near Chittoor')">🌫 Air quality — Chittoor</button>
      <button class="ex-chip traffic" onclick="sendQuery('Live road network and slope terrain near Kurnool')">🛣 Roads + slope — Kurnool</button>
    </div>
  </div>

  <div class="chat-messages" id="chat"></div>

  <div class="suggestions" id="sugg-box" style="display:none">
    <div class="sugg-label">Follow-up</div>
    <div class="sugg-chips" id="sugg-chips"></div>
  </div>

  <div class="pipeline-strip" id="pipeline">
    <div class="pip-chip" id="pip-geocode_place">geocode</div>
    <div class="pip-chip" id="pip-fetch_osm_features">osm</div>
    <div class="pip-chip" id="pip-fetch_elevation_grid">elevation</div>
    <div class="pip-chip" id="pip-fetch_weather_realtime">weather</div>
    <div class="pip-chip" id="pip-fetch_disaster_alerts">disasters</div>
    <div class="pip-chip" id="pip-fetch_air_quality">air-quality</div>
    <div class="pip-chip" id="pip-fetch_live_traffic">traffic</div>
    <div class="pip-chip" id="pip-analyze_flood_prone">flood</div>
    <div class="pip-chip" id="pip-compute_slope">slope</div>
    <div class="pip-chip" id="pip-render_map">render-2d</div>
    <div class="pip-chip" id="pip-render_3d_terrain">render-3d</div>
  </div>

  <div class="input-area">
    <div class="input-row">
      <textarea id="q" placeholder="Ask anything… e.g. 'Show flood and weather near Tirupati' or 'Also show air quality'" rows="1"></textarea>
      <button class="send-btn" id="send-btn" onclick="submitQuery()" title="Send [Ctrl+Enter]">▶</button>
    </div>
  </div>

  <div class="cfg-row">
    <select id="model-sel">
      <option value="mistral">mistral</option>
      <option value="llama3.2">llama3.2</option>
      <option value="gemma3">gemma3</option>
      <option value="deepseek-r1">deepseek-r1</option>
    </select>
    <button class="apply-btn" onclick="applyConfig()">APPLY</button>
    <button class="clear-btn" onclick="clearMemory()">CLEAR MEM</button>
  </div>

</div>

<!-- ═══ MAP AREA ═══ -->
<div class="map-area">
  <div class="map-placeholder" id="placeholder">
    <span class="icon">🛰</span>
    Real-Time GeoAI Intelligence<br>
    <span style="font-size:10px;color:#1a2a3a">
      Weather · Disasters · Air Quality · Traffic · DEM · 3D Terrain
    </span><br>
    <span style="font-size:10px;color:#1a2a3a">
      Type a query or pick a quick example →
    </span>
  </div>
  <iframe id="map-frame" src="about:blank"></iframe>

  <div class="view-switch" id="view-switch">
    <button class="vbtn" id="vbtn-2d" onclick="switchView('2d')">2D MAP</button>
    <button class="vbtn" id="vbtn-3d" onclick="switchView('3d')">3D TERRAIN</button>
  </div>

  <div id="status-chip">Step <span id="sc">0</span></div>
  <div class="progress"><div class="progress-fill" id="prog"></div></div>
</div>

<script>
const socket = io();
const TOOL_IDS = [
  'geocode_place','fetch_osm_features','fetch_elevation_grid',
  'fetch_weather_realtime','fetch_disaster_alerts','fetch_air_quality',
  'fetch_live_traffic','analyze_flood_prone','compute_slope',
  'render_map','render_3d_terrain'
];

let running = false, stepCount = 0;
let map2dPath = null, map3dPath = null, currentView = '2d';

// ── Socket events ────────────────────────────────────────────────
socket.on('connected', d => {
  document.getElementById('hdr-model').textContent =
    (d.model||'MISTRAL').toUpperCase() + ' · LOCAL';
  if (d.history && d.history.length > 0) {
    d.history.forEach(m => appendMessage(m.role, m.text, m.meta));
  }
});

socket.on('chat_message', m => {
  removeTyping();
  appendMessage(m.role, m.text, m.meta);
});

socket.on('agent_step', s => {
  stepCount++;
  document.getElementById('sc').textContent = stepCount;
  updatePipeline(s.tool, s.level);
  updateProgress(s.tool);
});

socket.on('suggestions', chips => {
  showSuggestions(chips);
});

socket.on('map_ready', d => {
  document.getElementById('placeholder').style.display = 'none';
  if (d.type === '3d') {
    map3dPath = d.path + '?t=' + Date.now();
  } else {
    map2dPath = d.path + '?t=' + Date.now();
  }
  switchView(d.type);
  document.getElementById('view-switch').style.display = 'flex';
});

socket.on('agent_done', d => {
  setRunning(false);
  document.getElementById('prog').style.width = '100%';
  setTimeout(() => document.getElementById('prog').style.width = '0%', 1500);
});

socket.on('agent_error', d => {
  removeTyping();
  appendMessage('agent', '⚠ Error: ' + d.error.split('\n')[0], {type:'error'});
  setRunning(false);
  document.getElementById('pulse').className = 'pulse err';
});

socket.on('restore_chat', d => {
  document.getElementById('chat').innerHTML = '';
  d.messages.forEach(m => appendMessage(m.role, m.text, m.meta));
});

// ── UI Helpers ────────────────────────────────────────────────────
function setRunning(v) {
  running = v;
  document.getElementById('send-btn').disabled = v;
  document.getElementById('pulse').className = 'pulse' + (v ? ' on' : '');
  document.getElementById('status-chip').style.display = v ? 'block' : 'none';
  if (!v) stepCount = 0;
}

function resetPipeline() {
  TOOL_IDS.forEach(t => {
    const el = document.getElementById('pip-' + t);
    if (el) el.className = 'pip-chip';
  });
}

function updatePipeline(toolName, level) {
  const el = document.getElementById('pip-' + toolName);
  if (!el) return;
  if (level === 'success') el.className = 'pip-chip done';
  else if (level === 'error') el.className = 'pip-chip err';
  else el.className = 'pip-chip active';
}

function updateProgress(toolName) {
  const idx = TOOL_IDS.indexOf(toolName);
  if (idx < 0) return;
  const pct = ((idx + 1) / TOOL_IDS.length) * 85;
  document.getElementById('prog').style.width = pct + '%';
}

function appendMessage(role, text, meta) {
  const chat = document.getElementById('chat');
  const isAgent = role === 'agent';
  const now = new Date().toLocaleTimeString('en',{hour:'2-digit',minute:'2-digit'});

  const wrapper = document.createElement('div');
  wrapper.className = 'msg ' + (isAgent ? 'agent' : 'user');

  let innerHtml = '';
  if (meta && meta.type === 'intent_echo') {
    innerHtml = `<span class="intent-tag">INTENT PARSED</span><br>${escHtml(text)}`;
  } else if (meta && meta.tool) {
    innerHtml = `<span class="tool-tag">${escHtml(meta.tool)}</span><br>${escHtml(text)}`;
  } else {
    innerHtml = escHtml(text);
  }

  wrapper.innerHTML = `
    <div class="avatar ${isAgent?'agent':'user'}">${isAgent?'⬡':'U'}</div>
    <div>
      <div class="bubble">${innerHtml}</div>
      <div class="msg-time">${now}</div>
    </div>`;
  chat.appendChild(wrapper);
  chat.scrollTop = chat.scrollHeight;
}

function addTyping() {
  const chat = document.getElementById('chat');
  const div  = document.createElement('div');
  div.className = 'msg agent';
  div.id = 'typing-indicator';
  div.innerHTML = `
    <div class="avatar agent">⬡</div>
    <div>
      <div class="bubble">
        <div class="typing">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>`;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typing-indicator');
  if (el) el.remove();
}

function showSuggestions(chips) {
  if (!chips || !chips.length) return;
  const box   = document.getElementById('sugg-box');
  const inner = document.getElementById('sugg-chips');
  inner.innerHTML = '';
  chips.slice(0, 4).forEach(c => {
    const btn = document.createElement('button');
    btn.className = 'sugg-chip';
    btn.textContent = c;
    btn.onclick = () => sendQuery(c);
    inner.appendChild(btn);
  });
  box.style.display = 'block';
}

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function switchView(type) {
  currentView = type;
  const frame = document.getElementById('map-frame');
  if (type === '3d' && map3dPath) {
    frame.src = map3dPath;
  } else if (type === '2d' && map2dPath) {
    frame.src = map2dPath;
  }
  frame.style.display = 'block';
  document.getElementById('vbtn-2d').classList.toggle('active', type === '2d');
  document.getElementById('vbtn-3d').classList.toggle('active', type === '3d');
}

// ── Query submission ──────────────────────────────────────────────
async function submitQuery() {
  const ta = document.getElementById('q');
  const q  = ta.value.trim();
  if (!q || running) return;
  ta.value = '';
  ta.style.height = '40px';
  sendQuery(q);
}

async function sendQuery(q) {
  if (!q || running) return;
  document.getElementById('sugg-box').style.display = 'none';
  resetPipeline();
  setRunning(true);
  stepCount = 0;

  appendMessage('user', q, {});
  addTyping();

  try {
    const r = await fetch('/api/query', {
      method : 'POST',
      headers: {'Content-Type': 'application/json'},
      body   : JSON.stringify({query: q}),
    });
    if (!r.ok) {
      const e = await r.json();
      removeTyping();
      appendMessage('agent', '⚠ ' + (e.error || 'Server error'), {type:'error'});
      setRunning(false);
    }
  } catch(e) {
    removeTyping();
    appendMessage('agent', '⚠ Network error: ' + e.message, {type:'error'});
    setRunning(false);
  }
}

function sendQuery(q) {
  if (!q || running) return;
  document.getElementById('sugg-box').style.display = 'none';
  resetPipeline();
  setRunning(true);
  stepCount = 0;
  appendMessage('user', q, {});
  addTyping();
  fetch('/api/query', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query: q}),
  }).then(r => {
    if (!r.ok) return r.json().then(e => {
      removeTyping();
      appendMessage('agent', '⚠ ' + (e.error || 'Server error'), {type:'error'});
      setRunning(false);
    });
  }).catch(e => {
    removeTyping();
    appendMessage('agent', '⚠ Network: ' + e.message, {type:'error'});
    setRunning(false);
  });
}

async function applyConfig() {
  const model = document.getElementById('model-sel').value;
  await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({model}),
  });
  document.getElementById('hdr-model').textContent = model.toUpperCase() + ' · LOCAL';
}

async function clearMemory() {
  await fetch('/api/clear_memory', {method: 'POST'});
  document.getElementById('chat').innerHTML = '';
  document.getElementById('sugg-box').style.display = 'none';
  appendMessage('agent', 'Session memory cleared. Ready for a fresh query.', {});
}

// ── Textarea auto-resize + Ctrl+Enter ────────────────────────────
const ta = document.getElementById('q');
ta.addEventListener('input', () => {
  ta.style.height = '40px';
  ta.style.height = Math.min(ta.scrollHeight, 100) + 'px';
});
ta.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); submitQuery(); }
  if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) { e.preventDefault(); submitQuery(); }
});

// ── Welcome message ──────────────────────────────────────────────
window.addEventListener('load', () => {
  if (!document.querySelector('.msg')) {
    appendMessage('agent',
      'Hello! I\'m GeoAI — your real-time geospatial intelligence agent.\n\n' +
      'I can analyze flood risk, weather, air quality, disasters, road networks, and 3D terrain for any location.\n\n' +
      'Try: "Show flood risk and weather near Tirupati" or pick a quick query above.',
      {type: 'welcome'}
    );
  }
});
</script>
</body>
</html>"""

# 11 | ENTRYPOINT
if __name__ == "__main__":
    banner = f"""
╔══════════════════════════════════════════════════════╗
║           GEO·AI AGENT  v2.0  — Real-Time Edition    ║
║   Conversational Text → LLM → Live GIS → 3D Map      ║
╠══════════════════════════════════════════════════════╣
║  Model     : {CFG['OLLAMA_MODEL']:<38}               ║
║  Weather   : Open-Meteo  (live, no key)              ║
║  Disasters : GDACS RSS + ReliefWeb                   ║
║  Air Qual  : OpenAQ v3   (live, no key)              ║
║  Traffic   : OSM Overpass API                        ║
║  DEM       : opentopodata.org SRTM 30m               ║
║  3D Terrain: deck.gl TerrainLayer                    ║
╠══════════════════════════════════════════════════════╣
║  Tools: {len(TOOL_REGISTRY):<44}                     ║
║  {', '.join(TOOL_REGISTRY.keys())[:50]:<50}          ║
╠══════════════════════════════════════════════════════╣
║  http://localhost:{CFG['PORT']}                      ║
╚══════════════════════════════════════════════════════╝"""
    print(banner)
    sio.run(app, host=CFG["HOST"], port=CFG["PORT"], debug=CFG["DEBUG"])