# GEOAI 3D MAP WITH CONTEXT-AWARE LOCAL AI - Knows Everything About Your Map!
import os
import json
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS
from shapely.geometry import shape
import geopandas as gpd
import requests

try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False

app = Flask(__name__)
CORS(app)

OUTPUT_FOLDER = "outputs"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# LOCAL GGUF MODEL PATH
GGUF_MODEL_PATH = "/Volumes/PENDRIVE/TIH/models/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"

MODEL_SETTINGS = {
    "n_ctx": 2048,
    "n_threads": 4,
    "n_gpu_layers": 0,
    "verbose": False
}

llm_model = None

def load_llm_model():
    """Load the local GGUF model"""
    global llm_model
    
    if llm_model is not None:
        return llm_model
    
    if not LLAMA_CPP_AVAILABLE:
        print("❌ llama-cpp-python not installed!")
        return None
    
    if not os.path.exists(GGUF_MODEL_PATH):
        print(f"❌ GGUF model not found: {GGUF_MODEL_PATH}")
        return None
    
    try:
        print(f"🔄 Loading local TinyLlama model...")
        llm_model = Llama(model_path=GGUF_MODEL_PATH, **MODEL_SETTINGS)
        print("✅ Local AI model loaded!")
        return llm_model
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        return None

# CONTEXT-AWARE AI CHATBOT
def chat_with_ai(user_message, conversation_history=None, context=None):
    """AI that knows about the map, buildings, and statistics"""
    
    model = load_llm_model()
    
    if model is None:
        return {
            "response": "🔧 AI model not loaded. Please check setup instructions.",
            "action": None
        }
    
    # Extract detailed context from map data
    buildings_info = ""
    avg_height = 0
    max_height = 0
    min_height = 0
    total_area = 0
    category_counts = {}
    tallest_list = []
    
    if context and context.get('buildings_data'):
        buildings = context['buildings_data']['features']
        
        # Calculate statistics
        heights = [b['properties']['height'] for b in buildings]
        areas = [b['properties'].get('area_sqm', 0) for b in buildings]
        categories = [b['properties']['category'] for b in buildings]
        
        avg_height = sum(heights) / len(heights) if heights else 0
        max_height = max(heights) if heights else 0
        min_height = min(heights) if heights else 0
        total_area = sum(areas)
        
        tallest_buildings = sorted(buildings, key=lambda x: x['properties']['height'], reverse=True)[:3]
        
        # Category counts
        from collections import Counter
        category_counts = Counter(categories)
        
        # Build rich context
        buildings_info = f"""
CURRENT MAP DATA:
Location: {context.get('location', 'Unknown')}
Total Buildings: {len(buildings)}
Average Height: {avg_height:.1f}m
Tallest Building: {max_height:.0f}m
Shortest Building: {min_height:.0f}m
Total Area: {total_area:,.0f}m²

BUILDING CATEGORIES:
"""
        for cat, count in category_counts.most_common():
            buildings_info += f"- {cat.title()}: {count} buildings\n"
        
        buildings_info += """
TOP 3 TALLEST BUILDINGS:
"""
        for i, b in enumerate(tallest_buildings, 1):
            name = b['properties'].get('name') or f"Building #{b['properties']['id']}"
            height = b['properties']['height']
            floors = b['properties']['floors']
            buildings_info += f"{i}. {name}: {height}m ({floors} floors)\n"
        
        tallest_list = tallest_buildings
    
    # Build enhanced system prompt with map context
    system_context = f"""You are GeoBot, an intelligent assistant with FULL KNOWLEDGE of the current 3D map.

{buildings_info}

CAPABILITIES:
- Answer questions about buildings on THIS map (use the data above!)
- Provide statistics about the visible area
- Compare buildings by height, area, or type
- Explain building categories and distributions
- Search for new locations when requested

SEARCH COMMAND:
When user wants to see a different place: SEARCH:<place_name>

INSTRUCTIONS:
- Use the MAP DATA above to answer questions
- Be specific with numbers and facts
- Reference actual buildings from the data
- Keep responses concise (2-4 sentences)
- Use emojis occasionally 🏙️ 📊 🏗️

EXAMPLE RESPONSES:
User: "What's the tallest building?"
You: "The tallest building here is {max_height}m tall with multiple floors!"

User: "How many buildings are there?"
You: "There are {context.get('building_count', 0) if context else 0} buildings visible on this map."

User: "Tell me about the buildings"
You: "This area has {context.get('building_count', 0) if context else 0} buildings. The average height is {avg_height:.1f}m."
"""
    
    conversation = conversation_history or []
    prompt = f"<|system|>\n{system_context}</s>\n"
    
    # Add recent conversation
    recent = conversation[-4:] if len(conversation) > 4 else conversation
    for msg in recent:
        role = "user" if msg["role"] == "user" else "assistant"
        prompt += f"<|{role}|>\n{msg['content']}</s>\n"
    
    prompt += f"<|user|>\n{user_message}</s>\n<|assistant|>\n"
    
    try:
        response = model(
            prompt,
            max_tokens=250,
            temperature=0.7,
            top_p=0.9,
            top_k=40,
            repeat_penalty=1.2,
            stop=["</s>", "<|user|>", "<|system|>"],
            echo=False
        )
        
        ai_response = response['choices'][0]['text'].strip()
        ai_response = ai_response.replace("</s>", "").replace("<|", "").strip()
        
        # Check for search intent
        if "SEARCH:" in ai_response.upper():
            parts = ai_response.upper().split("SEARCH:")
            if len(parts) > 1:
                location = parts[1].strip().split("\n")[0].strip()
                location = location.replace('"', '').replace("'", "")
                return {
                    "response": f"🌍 Searching for {location}...",
                    "action": "search",
                    "location": location
                }
        
        # Use fallback if response is poor
        if not ai_response or len(ai_response) < 15:
            ai_response = get_smart_fallback(user_message, context)
        
        return {"response": ai_response, "action": None}
        
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return {"response": get_smart_fallback(user_message, context), "action": None}

def get_smart_fallback(user_message, context):
    """Smart fallback responses using actual map data"""
    user_lower = user_message.lower()
    
    if not context or not context.get('buildings_data'):
        return "🌍 I can see the map, but I need building data to answer that question!"
    
    buildings = context['buildings_data']['features']
    heights = [b['properties']['height'] for b in buildings]
    areas = [b['properties'].get('area_sqm', 0) for b in buildings]
    
    from collections import Counter
    categories = [b['properties']['category'] for b in buildings]
    category_counts = Counter(categories)
    
    # Pre-calculate values
    num_buildings = len(buildings)
    avg_height = sum(heights) / len(heights) if heights else 0
    max_height = max(heights) if heights else 0
    min_height = min(heights) if heights else 0
    total_area = sum(areas)
    location = context.get('location', 'this area')
    
    # Tallest building question
    if any(word in user_lower for word in ["tallest", "highest", "tall building"]):
        tallest = max(buildings, key=lambda x: x['properties']['height'])
        name = tallest['properties'].get('name') or f"Building #{tallest['properties']['id']}"
        height_val = tallest['properties']['height']
        floors_val = tallest['properties']['floors']
        return f"🏗️ The tallest building here is **{name}** at {height_val}m with {floors_val} floors!"
    
    # Count question
    if any(word in user_lower for word in ["how many", "number of", "count"]):
        return f"📊 There are **{num_buildings} buildings** visible on this map in {location}."
    
    # Overview/summary
    if any(word in user_lower for word in ["overview", "summary", "tell me about", "describe"]):
        main_category = category_counts.most_common(1)[0] if category_counts else ("other", 0)
        return f"🏙️ This area has **{num_buildings} buildings** (mostly {main_category[0]}) with an average height of {avg_height:.1f}m. The tallest reaches {max_height:.0f}m!"
    
    # Statistics
    if any(word in user_lower for word in ["stats", "statistics", "data", "numbers"]):
        return f"📊 **Map Statistics:**\n• Buildings: {num_buildings}\n• Avg Height: {avg_height:.1f}m\n• Total Area: {total_area:,.0f}m²\n• Categories: {len(category_counts)}"
    
    # Categories
    if any(word in user_lower for word in ["type", "category", "categories", "kinds"]):
        cat_list = ", ".join([f"{cat} ({count})" for cat, count in category_counts.most_common(3)])
        return f"🏘️ Building types: {cat_list}"
    
    # Shortest
    if any(word in user_lower for word in ["shortest", "smallest", "lowest"]):
        shortest = min(buildings, key=lambda x: x['properties']['height'])
        short_height = shortest['properties']['height']
        return f"🏠 The shortest building is {short_height}m tall."
    
    # Average
    if any(word in user_lower for word in ["average", "mean"]):
        return f"📏 The average building height here is {avg_height:.1f}m."
    
    # Location question
    if any(word in user_lower for word in ["where", "location", "place"]):
        return f"📍 You're viewing **{location}** with {num_buildings} buildings."
    
    # Search intent
    if any(word in user_lower for word in ["show", "find", "search", "go to", "visit"]):
        words = user_message.split()
        if len(words) > 1:
            search_location = " ".join(words[1:])
            return f"🔍 To search for '{search_location}', type it in the search bar above!"
    
    # Greetings
    if any(word in user_lower for word in ["hello", "hi", "hey"]):
        return f"👋 Hello! I can see {num_buildings} buildings in {location}. What would you like to know?"
    
    # Help
    if "help" in user_lower:
        return "🤖 Ask me:\n• 'What's the tallest building?'\n• 'How many buildings?'\n• 'Give me an overview'\n• 'Show building statistics'"
    
    # Default with context
    return f"🌍 I can see {num_buildings} buildings in {location}. Try asking about the tallest building, statistics, or building types!"

def search_place(place_name):
    """Search for a place"""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": place_name, "format": "json", "limit": 1, "addressdetails": 1}
    headers = {"User-Agent": "GeoAI-Context-Aware-App/1.0"}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.ok and response.json():
            data = response.json()[0]
            return {
                "name": data["display_name"],
                "lat": float(data["lat"]),
                "lon": float(data["lon"]),
                "type": data.get("type", "place")
            }
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None

def get_buildings_accurate(lat, lon, radius=800):
    """Get building data from OpenStreetMap"""
    overpass_query = f"""
    [out:json][timeout:30];
    (
      way["building"](around:{radius},{lat},{lon});
      relation["building"]["type"="multipolygon"](around:{radius},{lat},{lon});
    );
    out geom;
    >;
    out skel qt;
    """
    
    url = "https://overpass-api.de/api/interpreter"
    
    try:
        print(f"Fetching buildings...")
        response = requests.post(url, data={"data": overpass_query}, headers={"User-Agent": "GeoAI-App/1.0"}, timeout=35)
        
        if not response.ok:
            return None
        
        data = response.json()
        elements = data.get("elements", [])
        
        if not elements:
            return None
        
        buildings = []
        building_id = 1
        
        for element in elements:
            if element.get("type") != "way" or "geometry" not in element:
                continue
            
            coords = [[n["lon"], n["lat"]] for n in element["geometry"] if "lat" in n and "lon" in n]
            
            if len(coords) < 3:
                continue
            
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            
            tags = element.get("tags", {})
            if "building" not in tags:
                continue
            
            height = calculate_height(tags)
            
            try:
                poly = shape({"type": "Polygon", "coordinates": [coords]})
                area_sqm = calculate_area_sqm(poly, lat, lon)
            except:
                area_sqm = 0
            
            category = categorize_building(tags.get("building", "yes"), tags.get("amenity", ""), tags.get("shop", ""))
            
            buildings.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {
                    "id": building_id,
                    "name": tags.get("name", ""),
                    "height": round(height, 1),
                    "floors": max(1, int(height / 3.5)),
                    "building_type": tags.get("building", "yes"),
                    "category": category,
                    "area_sqm": round(area_sqm, 2),
                    "amenity": tags.get("amenity", ""),
                    "confidence": 0.9 if "height" in tags else 0.7
                }
            })
            building_id += 1
        
        if not buildings:
            return None
        
        print(f"✅ Found {len(buildings)} buildings!")
        return {"type": "FeatureCollection", "features": buildings}
        
    except Exception as e:
        print(f"Error: {e}")
        return None

def calculate_height(tags):
    if "height" in tags:
        try:
            h = tags["height"].lower().replace("m", "").strip()
            return float(h)
        except:
            pass
    if "building:levels" in tags:
        try:
            return float(tags["building:levels"]) * 3.5
        except:
            pass
    building_type = tags.get("building", "").lower()
    if "tower" in building_type or "skyscraper" in building_type:
        return 100
    if "church" in building_type or "cathedral" in building_type:
        return 25
    if "office" in building_type or "commercial" in building_type:
        return 28
    if "apartments" in building_type:
        return 24
    if "house" in building_type or "residential" in building_type:
        return 9
    return 10

def calculate_area_sqm(polygon, lat, lon):
    try:
        gdf = gpd.GeoDataFrame([1], geometry=[polygon], crs="EPSG:4326")
        utm_zone = int((lon + 180) / 6) + 1
        utm_crs = f"EPSG:326{utm_zone}" if lat >= 0 else f"EPSG:327{utm_zone}"
        gdf_proj = gdf.to_crs(utm_crs)
        return gdf_proj.geometry.area.values[0]
    except:
        return polygon.area * 111320 * 111320 * np.cos(np.radians(lat))

def categorize_building(building_type, amenity, shop):
    bt = building_type.lower()
    if any(x in bt for x in ["tower", "skyscraper", "office", "commercial"]):
        return "commercial"
    if any(x in bt for x in ["apartments", "residential", "house"]):
        return "residential"
    if amenity or shop:
        return "retail"
    if "industrial" in bt or "warehouse" in bt:
        return "industrial"
    if "church" in bt or "mosque" in bt or "temple" in bt:
        return "religious"
    if "school" in bt or "hospital" in bt:
        return "public"
    return "other"

def create_realistic_buildings(lat, lon, num_buildings=80):
    """Generate buildings when OSM unavailable"""
    buildings = []
    num_clusters = np.random.randint(4, 7)
    
    for _ in range(num_clusters):
        cluster_x = np.random.uniform(-0.004, 0.004)
        cluster_y = np.random.uniform(-0.004, 0.004)
        cluster_type = np.random.choice(["downtown", "residential", "mixed"])
        
        for i in range(num_buildings // num_clusters):
            spread = 0.0015 if cluster_type == "downtown" else 0.002
            dx = np.random.normal(cluster_x, spread)
            dy = np.random.normal(cluster_y, spread)
            
            if cluster_type == "downtown":
                height = np.random.randint(40, 120) if np.random.random() < 0.3 else np.random.randint(20, 45)
                size = np.random.uniform(0.00015, 0.0004) if height > 40 else np.random.uniform(0.0001, 0.0002)
                category = "commercial"
            elif cluster_type == "residential":
                height = np.random.randint(8, 25)
                size = np.random.uniform(0.00008, 0.00015)
                category = "residential"
            else:
                height = np.random.randint(10, 35)
                size = np.random.uniform(0.00009, 0.00018)
                category = np.random.choice(["residential", "commercial", "retail"])
            
            angle = np.random.uniform(0, np.pi / 4)
            aspect = np.random.uniform(0.6, 1.4)
            corners = [(-size, -size*aspect), (size, -size*aspect), (size, size*aspect), (-size, size*aspect), (-size, -size*aspect)]
            coords = []
            for x, y in corners:
                rx = x * np.cos(angle) - y * np.sin(angle)
                ry = x * np.sin(angle) + y * np.cos(angle)
                coords.append([lon + dx + rx, lat + dy + ry])
            
            buildings.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {
                    "id": len(buildings) + 1,
                    "name": f"Building {len(buildings) + 1}",
                    "height": height,
                    "floors": max(1, height // 3),
                    "building_type": category,
                    "category": category,
                    "area_sqm": size * size * 111320 * 111320 * 4,
                    "confidence": 0.7,
                    "amenity": "",
                    "shop": ""
                }
            })
    
    return {"type": "FeatureCollection", "features": buildings}

def create_map_with_chatbot(place, buildings_data):
    """Create map with context-aware chatbot"""
    
    num_buildings = len(buildings_data["features"])
    heights = [f["properties"]["height"] for f in buildings_data["features"]]
    avg_height = sum(heights) / len(heights) if heights else 0
    max_height = max(heights) if heights else 0
    areas = [f["properties"].get("area_sqm", 0) for f in buildings_data["features"]]
    total_area = sum(areas)
    
    model_status = "✅ Ready" if llm_model is not None else "⚠️ Not Loaded"
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>GeoAI 3D Map - {place['name']}</title>
    
    <script src="https://unpkg.com/deck.gl@8.9.0/dist.min.js"></script>
    <script src="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.js"></script>
    <link href="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.css" rel="stylesheet"/>
    
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            overflow: hidden;
        }}
        #header {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            padding: 15px 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        #header h1 {{
            margin: 0 0 10px 0;
            font-size: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .ai-badge {{
            background: rgba(255,255,255,0.25);
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        #stats {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }}
        .stat {{
            background: rgba(255,255,255,0.2);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
        }}
        .stat-value {{
            font-weight: bold;
            font-size: 16px;
        }}
        #map {{
            width: 100vw;
            height: calc(100vh - 130px);
        }}
        #chatbot {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 400px;
            height: 600px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            display: flex;
            flex-direction: column;
            z-index: 1000;
            transition: all 0.3s;
        }}
        #chatbot.minimized {{ height: 60px; }}
        #chat-header {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            padding: 15px;
            border-radius: 16px 16px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
        }}
        #chat-header h3 {{
            margin: 0;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            background: #22c55e;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        #chat-toggle {{
            background: none;
            border: none;
            color: white;
            font-size: 24px;
            cursor: pointer;
            padding: 0;
            width: 30px;
            height: 30px;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        #chat-messages {{
            flex: 1;
            overflow-y: auto;
            padding: 15px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: #f9fafb;
        }}
        #chat-messages::-webkit-scrollbar {{ width: 6px; }}
        #chat-messages::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
        .message {{
            max-width: 85%;
            padding: 12px 16px;
            border-radius: 14px;
            font-size: 14px;
            line-height: 1.5;
            animation: slideIn 0.3s ease;
        }}
        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .message.user {{
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }}
        .message.ai {{
            background: white;
            color: #1f2937;
            align-self: flex-start;
            border-bottom-left-radius: 4px;
            border: 1px solid #e5e7eb;
            white-space: pre-wrap;
        }}
        .message.system {{
            background: #dbeafe;
            color: #1e40af;
            align-self: center;
            font-size: 13px;
            text-align: center;
        }}
        #chat-input-area {{
            padding: 15px;
            border-top: 1px solid #e5e7eb;
            background: white;
            display: flex;
            gap: 10px;
            border-radius: 0 0 16px 16px;
        }}
        #chat-input {{
            flex: 1;
            padding: 12px;
            border: 2px solid #e5e7eb;
            border-radius: 10px;
            font-size: 14px;
            font-family: inherit;
        }}
        #chat-input:focus {{
            outline: none;
            border-color: #10b981;
        }}
        #chat-send {{
            padding: 12px 20px;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
        }}
        #chat-send:hover {{ opacity: 0.9; }}
        #chat-send:disabled {{
            background: #9ca3af;
            cursor: not-allowed;
        }}
        .typing {{
            padding: 12px 16px;
            background: white;
            border-radius: 14px;
            align-self: flex-start;
            font-size: 14px;
            color: #6b7280;
            border: 1px solid #e5e7eb;
        }}
        .typing::after {{
            content: '...';
            animation: typing 1.4s infinite;
        }}
        @keyframes typing {{
            0%, 20% {{ content: '.'; }}
            40% {{ content: '..'; }}
            60%, 100% {{ content: '...'; }}
        }}
        #legend {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            background: white;
            padding: 16px;
            border-radius: 12px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.15);
            z-index: 100;
        }}
        .legend-title {{
            font-weight: 700;
            margin-bottom: 12px;
            font-size: 14px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
            font-size: 13px;
        }}
        .legend-color {{
            width: 24px;
            height: 24px;
            border-radius: 6px;
        }}
        .quick-suggestions {{
            padding: 10px 15px;
            background: #f0fdf4;
            border-bottom: 1px solid #d1fae5;
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .suggestion-btn {{
            padding: 6px 12px;
            background: white;
            border: 1px solid #10b981;
            color: #047857;
            border-radius: 8px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .suggestion-btn:hover {{
            background: #10b981;
            color: white;
        }}
    </style>
</head>
<body>
    <div id="header">
        <h1>
            🌍 {place['name']}
            <span class="ai-badge">🧠 AI: {model_status}</span>
        </h1>
        <div id="stats">
            <div class="stat"><div>Buildings</div><div class="stat-value">{num_buildings}</div></div>
            <div class="stat"><div>Avg Height</div><div class="stat-value">{avg_height:.1f}m</div></div>
            <div class="stat"><div>Max Height</div><div class="stat-value">{max_height:.0f}m</div></div>
            <div class="stat"><div>Total Area</div><div class="stat-value">{total_area:,.0f}m²</div></div>
        </div>
    </div>
    
    <div id="map"></div>
    
    <div id="legend">
        <div class="legend-title">📊 Height</div>
        <div class="legend-item">
            <div class="legend-color" style="background: #ef4444;"></div>
            <span>Tall (30m+)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #f59e0b;"></div>
            <span>Medium (15-30m)</span>
        </div>
        <div class="legend-item">
            <div class="legend-color" style="background: #3b82f6;"></div>
            <span>Short (&lt;15m)</span>
        </div>
    </div>
    
    <div id="chatbot">
        <div id="chat-header" onclick="toggleChat()">
            <h3><span class="status-dot"></span>🧠 AI</h3>
            <button id="chat-toggle">−</button>
        </div>
        <div class="quick-suggestions">
            <button class="suggestion-btn" onclick="askQuestion('What\\'s the tallest building?')">🏗️ Tallest</button>
            <button class="suggestion-btn" onclick="askQuestion('Give me an overview')">📊 Overview</button>
            <button class="suggestion-btn" onclick="askQuestion('Building statistics')">📈 Stats</button>
            <button class="suggestion-btn" onclick="askQuestion('Building types')">🏘️ Types</button>
        </div>
        <div id="chat-messages">
            <div class="message ai">👋 Hi! I'm your AI assistant!

🧠 I can see ALL {num_buildings} buildings on this map and know their details!

Try asking:
• "What's the tallest building?"
• "Give me an overview"
• "How many commercial buildings?"
• "Building statistics"

Or click the quick suggestions above! ⬆️</div>
        </div>
        <div id="chat-input-area">
            <input id="chat-input" type="text" placeholder="Ask about the buildings..."/>
            <button id="chat-send" onclick="sendMessage()">Send</button>
        </div>
    </div>
    
    <script>
        const buildingsData = {json.dumps(buildings_data)};
        const currentLocation = {{
            name: "{place['name']}",
            lat: {place['lat']},
            lon: {place['lon']},
            building_count: {num_buildings},
            buildings_data: buildingsData
        }};
        
        let chatMinimized = false;
        let conversationHistory = [];
        let isProcessing = false;
        
        function toggleChat() {{
            chatMinimized = !chatMinimized;
            document.getElementById('chatbot').classList.toggle('minimized');
            document.getElementById('chat-toggle').textContent = chatMinimized ? '+' : '−';
        }}
        
        function askQuestion(question) {{
            document.getElementById('chat-input').value = question;
            sendMessage();
        }}
        
        async function sendMessage() {{
            if (isProcessing) return;
            
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;
            
            addMessage(message, 'user');
            input.value = '';
            
            const typingDiv = document.createElement('div');
            typingDiv.className = 'typing';
            typingDiv.id = 'typing-indicator';
            typingDiv.textContent = 'AI is analyzing the map';
            document.getElementById('chat-messages').appendChild(typingDiv);
            
            isProcessing = true;
            document.getElementById('chat-send').disabled = true;
            document.getElementById('chat-input').disabled = true;
            
            try {{
                const response = await fetch('/api/chat', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ 
                        message: message,
                        history: conversationHistory,
                        context: currentLocation
                    }})
                }});
                
                const data = await response.json();
                
                const typing = document.getElementById('typing-indicator');
                if (typing) typing.remove();
                
                addMessage(data.response, 'ai');
                
                if (data.action === 'search' && data.location) {{
                    addMessage(`🔍 Searching for ${{data.location}}...`, 'system');
                    setTimeout(() => {{
                        window.location.href = `/search?q=${{encodeURIComponent(data.location)}}`;
                    }}, 1500);
                }}
                
            }} catch (error) {{
                const typing = document.getElementById('typing-indicator');
                if (typing) typing.remove();
                addMessage('❌ Error: ' + error.message, 'system');
            }}
            
            isProcessing = false;
            document.getElementById('chat-send').disabled = false;
            document.getElementById('chat-input').disabled = false;
            document.getElementById('chat-input').focus();
        }}
        
        function addMessage(text, type) {{
            const msgDiv = document.createElement('div');
            msgDiv.className = `message ${{type}}`;
            msgDiv.textContent = text;
            document.getElementById('chat-messages').appendChild(msgDiv);
            msgDiv.scrollIntoView({{ behavior: 'smooth' }});
            
            if (type === 'user' || type === 'ai') {{
                conversationHistory.push({{
                    role: type === 'user' ? 'user' : 'assistant',
                    content: text
                }});
                if (conversationHistory.length > 20) {{
                    conversationHistory = conversationHistory.slice(-20);
                }}
            }}
        }}
        
        document.getElementById('chat-input').addEventListener('keypress', (e) => {{
            if (e.key === 'Enter' && !isProcessing) sendMessage();
        }});
        
        function getColor(height) {{
            if (height > 30) return [239, 68, 68, 200];
            if (height > 15) return [245, 158, 11, 200];
            return [59, 130, 246, 200];
        }}
        
        new deck.DeckGL({{
            container: 'map',
            mapStyle: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
            initialViewState: {{
                longitude: {place['lon']},
                latitude: {place['lat']},
                zoom: 16.5,
                pitch: 60,
                bearing: -30
            }},
            controller: true,
            layers: [
                new deck.GeoJsonLayer({{
                    id: 'buildings',
                    data: buildingsData,
                    extruded: true,
                    pickable: true,
                    wireframe: true,
                    getElevation: f => f.properties.height * 3,
                    getFillColor: f => getColor(f.properties.height),
                    onClick: info => {{
                        if (info.object) {{
                            const p = info.object.properties;
                            const details = `${{p.name || 'Building #' + p.id}}\\n\\nHeight: ${{p.height}}m\\nFloors: ${{p.floors}}\\nArea: ${{p.area_sqm.toFixed(0)}}m²\\nType: ${{p.category}}`;
                            alert(details);
                            
                            // Ask AI about this building
                            const question = `Tell me about ${{p.name || 'building #' + p.id}}`;
                            document.getElementById('chat-input').value = question;
                        }}
                    }}
                }})
            ]
        }});
        
        console.log('🧠 Context-Aware AI initialized with', buildingsData.features.length, 'buildings');
    </script>
</body>
</html>
"""
    return html

# FLASK ROUTES
@app.route('/')
def home():
    """Home page"""
    model_loaded = llm_model is not None
    status = "✅ Loaded" if model_loaded else "⚠️ Not Loaded"
    
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>GeoAI 3D Map</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            padding: 50px;
            border-radius: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 700px;
            width: 100%;
        }}
        h1 {{
            color: #10b981;
            margin-bottom: 10px;
            font-size: 36px;
        }}
        .subtitle {{
            color: #059669;
            font-size: 20px;
            margin-bottom: 10px;
            font-weight: 600;
        }}
        .status {{
            background: {'#d1fae5' if model_loaded else '#fef3c7'};
            color: {'#065f46' if model_loaded else '#92400e'};
            padding: 12px 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            font-weight: 600;
            display: inline-block;
        }}
        p {{
            color: #666;
            margin-bottom: 20px;
            line-height: 1.7;
            font-size: 16px;
        }}
        .features {{
            background: #f0fdf4;
            padding: 24px;
            border-radius: 16px;
            margin-bottom: 24px;
            border: 2px solid #10b981;
        }}
        .features h3 {{
            color: #065f46;
            margin-bottom: 14px;
            font-size: 18px;
        }}
        .features ul {{
            margin-left: 20px;
            color: #047857;
            line-height: 2;
        }}
        .features strong {{
            color: #065f46;
        }}
        form {{
            display: flex;
            gap: 12px;
            margin-bottom: 30px;
        }}
        input {{
            flex: 1;
            padding: 16px 20px;
            border: 2px solid #e5e7eb;
            border-radius: 12px;
            font-size: 16px;
        }}
        input:focus {{
            outline: none;
            border-color: #10b981;
        }}
        button {{
            padding: 16px 32px;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
        }}
        button:hover {{ opacity: 0.9; }}
        .examples {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }}
        .examples a {{
            padding: 14px;
            background: #f3f4f6;
            color: #10b981;
            text-decoration: none;
            border-radius: 10px;
            text-align: center;
            font-weight: 600;
        }}
        .examples a:hover {{
            background: #10b981;
            color: white;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🌍 GeoAI 3D Map</h1>
        <div class="subtitle">🧠 with Local AI</div>
        <span class="status">🤖 AI Model: {status}</span>
        
        <p>Explore buildings in 3D with an AI that <strong>knows everything</strong> about the map!</p>
        
        <div class="features">
            <h3>🧠 AI Intelligence Features</h3>
            <ul>
                <li><strong>Full Map Awareness:</strong> AI knows all building data</li>
                <li><strong>Smart Answers:</strong> Ask about tallest, shortest, categories</li>
                <li><strong>Real Statistics:</strong> Get accurate numbers and facts</li>
                <li><strong>Context Memory:</strong> Maintains conversation context</li>
                <li><strong>100% Local:</strong> No API keys, runs offline</li>
            </ul>
        </div>
        
        <form action="/search" method="get">
            <input name="q" placeholder="Search any city or landmark..." required/>
            <button type="submit">🔍 Explore</button>
        </form>
        
        <div class="examples">
            <a href="/search?q=Chennai">Chennai</a>
            <a href="/search?q=Kolkata">Kolkata</a>
            <a href="/search?q=Mumbai">Mumbai</a>
            <a href="/search?q=Delhi">Delhi</a>
            <a href="/search?q=Tirupati">Tirupati</a>
            <a href="/search?q=Bangalore">Bangalore</a>
        </div>
    </div>
</body>
</html>
"""

@app.route('/search')
def search():
    """Search and display map"""
    query = request.args.get('q')
    if not query:
        return "Please provide a search query", 400
    
    print(f"\n🔍 Searching: {query}")
    place = search_place(query)
    
    if not place:
        return f"Could not find '{query}'", 404
    
    print(f"✅ Found: {place['name']}")
    
    buildings = get_buildings_accurate(place['lat'], place['lon'], radius=800)
    
    if not buildings or len(buildings['features']) == 0:
        print("⚠️ No OSM data, generating buildings...")
        buildings = create_realistic_buildings(place['lat'], place['lon'])
    else:
        print(f"✅ {len(buildings['features'])} buildings from OSM!")
    
    return create_map_with_chatbot(place, buildings)

@app.route('/api/chat', methods=['POST'])
def chat():
    """Context-aware chat endpoint"""
    try:
        data = request.json
        user_message = data.get('message', '')
        history = data.get('history', [])
        context = data.get('context', None)
        
        if not user_message:
            return jsonify({"error": "No message"}), 400
        
        print(f"\n💬 User: {user_message}")
        
        # Pass full context including building data
        ai_response = chat_with_ai(user_message, history, context)
        
        print(f"🧠 AI: {ai_response.get('response', '')[:100]}...")
        
        return jsonify(ai_response)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({
            "response": f"Sorry, I encountered an error: {str(e)}",
            "action": None
        }), 500

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "ok",
        "model_loaded": llm_model is not None,
        "model_path": GGUF_MODEL_PATH,
        "llama_cpp_installed": LLAMA_CPP_AVAILABLE,
        "features": {
            "context_aware": True,
            "building_analysis": True,
            "offline_ai": True
        }
    })

# START SERVER
if __name__ == '__main__':
   
    if not LLAMA_CPP_AVAILABLE:
        print("  ❌ llama-cpp-python not installed")
        print("  📦 Install: pip install llama-cpp-python")
    elif not os.path.exists(GGUF_MODEL_PATH):
        print(f"  ❌ GGUF model not found: {GGUF_MODEL_PATH}")
        print("  📥 Download from: https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF")
    else:
        print(f"  ✅ Model found: {GGUF_MODEL_PATH}")
        print("  🔄 Model will load on first chat message")
    
    print("\n🚀 Starting server on http://localhost:5500")    
    try:
        app.run(host='0.0.0.0', port=5500, debug=True)
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}")