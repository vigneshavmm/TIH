# INDIA POST DIGIPIN 
from flask import Flask, request, jsonify

app = Flask(__name__)

GRID = [['F','C','9','8'],['J','3','2','7'],['K','4','5','6'],['L','M','P','T']]
CHARS = {c: (r, col) for r, row in enumerate(GRID) for col, c in enumerate(row)}
BOUNDS = {'lat': (2.5, 38.5), 'lon': (63.5, 99.5)}

def encode_digipin(lat, lon, precision=10):
    """Encode lat/lon to DIGIPIN with specified precision (1-10 characters)"""
    if not (BOUNDS['lat'][0] <= lat <= BOUNDS['lat'][1] and BOUNDS['lon'][0] <= lon <= BOUNDS['lon'][1]):
        return None
    
    lat_min, lat_max = BOUNDS['lat']
    lon_min, lon_max = BOUNDS['lon']
    digipin = ""
    
    for _ in range(precision):
        lat_step, lon_step = (lat_max - lat_min) / 4, (lon_max - lon_min) / 4
        row = min(3, int((lat_max - lat) / lat_step))
        col = min(3, int((lon - lon_min) / lon_step))
        digipin += GRID[row][col]
        lat_max = lat_max - row * lat_step
        lat_min = lat_max - lat_step
        lon_min = lon_min + col * lon_step
        lon_max = lon_min + lon_step
    
    return digipin

def decode_digipin(digipin):
    digipin = digipin.replace('-', '').upper().strip()
    if not all(c in CHARS for c in digipin):
        return None
    
    lat_min, lat_max = BOUNDS['lat']
    lon_min, lon_max = BOUNDS['lon']
    
    for char in digipin:
        row, col = CHARS[char]
        lat_step, lon_step = (lat_max - lat_min) / 4, (lon_max - lon_min) / 4
        lat_max, lat_min = lat_max - row * lat_step, lat_max - (row + 1) * lat_step
        lon_min, lon_max = lon_min + col * lon_step, lon_min + (col + 1) * lon_step
    
    lat_diff = lat_max - lat_min
    lon_diff = lon_max - lon_min
    area_km2 = round(lat_diff * 111 * lon_diff * 111 * abs(((lat_min + lat_max) / 2) / 90), 2)
    
    return {
        "center_lat": round((lat_min + lat_max) / 2, 8),
        "center_lon": round((lon_min + lon_max) / 2, 8),
        "lat_min": round(lat_min, 8), "lat_max": round(lat_max, 8),
        "lon_min": round(lon_min, 8), "lon_max": round(lon_max, 8),
        "length": len(digipin),
        "precision_m": round(lat_diff * 111000, 2),
        "area_km2": area_km2
    }

@app.route("/")
def home():
    return """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>India Post DIGIPIN - Digital Address System</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,sans-serif;background:#f8fafc;height:100vh;display:flex;flex-direction:column;color:#1e293b}
.header{background:#ffffff;padding:20px 48px;border-bottom:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,0.05)}
.header-content{max-width:1600px;margin:0 auto;display:flex;align-items:center;justify-content:space-between}
.logo-section{display:flex;align-items:center;gap:16px}
.logo{width:48px;height:48px;background:#dc2626;border-radius:8px;display:flex;align-items:center;justify-content:center;color:white;font-weight:700;font-size:24px}
.title-group h1{font-size:1.5em;font-weight:700;color:#0f172a;margin-bottom:2px;letter-spacing:-0.5px}
.title-group p{font-size:0.875em;color:#64748b;font-weight:500}
.gov-badge{background:#fef3c7;color:#92400e;padding:4px 12px;border-radius:6px;font-size:0.75em;font-weight:600;border:1px solid #fde68a}
.container{flex:1;display:flex;padding:32px;gap:32px;max-width:1600px;margin:0 auto;width:100%}
.sidebar{width:400px;display:flex;flex-direction:column;gap:24px}
.panel{background:white;border-radius:12px;padding:24px;box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #e2e8f0}
.panel-header{font-size:0.875em;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:20px;padding-bottom:12px;border-bottom:2px solid #dc2626}
.input-group{margin-bottom:20px}
.input-label{font-size:0.75em;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;display:block}
#digipinInput{width:100%;padding:14px;font-size:20px;font-family:'Courier New',monospace;font-weight:600;text-align:center;border:2px solid #cbd5e1;border-radius:8px;letter-spacing:5px;text-transform:uppercase;transition:all 0.2s;background:#f8fafc}
#digipinInput:focus{outline:none;border-color:#dc2626;background:#ffffff;box-shadow:0 0 0 3px rgba(220,38,38,0.1)}
.input-hint{text-align:center;margin-top:8px;color:#94a3b8;font-size:0.8em}
.progress-bar{height:4px;background:#e2e8f0;border-radius:2px;overflow:hidden;margin:16px 0}
.progress-fill{height:100%;background:#dc2626;width:0%;transition:width 0.3s}
.char-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:20px 0;padding:16px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0}
.char-cell{aspect-ratio:1;background:white;border:2px solid #cbd5e1;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:1.3em;font-weight:700;color:#475569;font-family:'Courier New',monospace;cursor:pointer;transition:all 0.15s;user-select:none}
.char-cell:hover{background:#dc2626;color:white;border-color:#dc2626;transform:scale(1.05);box-shadow:0 4px 12px rgba(220,38,38,0.25)}
.char-cell:active{transform:scale(0.95)}
.char-cell.used{background:#dcfce7;border-color:#16a34a;color:#15803d}
#clearBtn{width:100%;padding:12px;margin-top:12px;background:#ef4444;color:white;border:none;border-radius:8px;font-weight:600;cursor:pointer;display:none;transition:all 0.2s;font-size:0.875em;letter-spacing:0.5px}
#clearBtn:hover{background:#dc2626;transform:translateY(-1px);box-shadow:0 4px 12px rgba(220,38,38,0.3)}
.info-grid{display:grid;gap:12px}
.info-card{background:#f8fafc;padding:14px;border-radius:8px;border-left:3px solid #dc2626}
.info-card label{font-size:0.7em;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px}
.info-card .value{font-size:1.1em;font-weight:700;color:#0f172a;font-family:'Courier New',monospace}
.examples{margin-top:16px}
.examples-header{font-size:0.8em;font-weight:700;color:#475569;margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px}
.example-btn{background:#ffffff;color:#475569;padding:12px;margin:8px 0;border-radius:8px;cursor:pointer;text-align:center;font-family:'Courier New',monospace;font-weight:600;transition:all 0.2s;border:1px solid #e2e8f0;font-size:0.9em}
.example-btn:hover{background:#dc2626;color:white;border-color:#dc2626;transform:translateY(-1px);box-shadow:0 4px 12px rgba(220,38,38,0.2)}
.map-container{flex:1;background:white;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);border:1px solid #e2e8f0;position:relative}
.map-header{padding:16px 20px;background:#fafafa;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center}
.map-title{font-size:0.875em;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:0.5px}
.map-instruction{font-size:0.75em;color:#64748b;font-weight:500}
#map{width:100%;height:calc(100% - 57px);cursor:crosshair}
.hover-popup{background:transparent!important;border:none!important}
.footer{background:#ffffff;padding:16px 48px;border-top:1px solid #e2e8f0;text-align:center}
.footer-text{font-size:0.75em;color:#94a3b8}
.footer-text a{color:#dc2626;text-decoration:none;font-weight:600}
</style></head><body>
<div class="header">
<div class="header-content">
<div class="logo-section">
<div class="logo">डि</div>
<div class="title-group">
<h1>India Post DIGIPIN</h1>
<p>Digital Geographic Identification & Pinpoint Navigation System</p>
</div>
</div>
<div class="gov-badge">GOVERNMENT OF INDIA</div>
</div>
</div>
<div class="container">
<div class="sidebar">
<div class="panel">
<div class="panel-header">Input DIGIPIN Code</div>
<div class="input-group">
<label class="input-label">Enter 10-Digit Code</label>
<input type="text" id="digipinInput" placeholder="TYPE HERE" maxlength="10" autocomplete="off" spellcheck="false"/>
<div class="input-hint">Click grid characters or type directly</div>
</div>
<div class="progress-bar"><div class="progress-fill" id="progress"></div></div>
<div class="char-grid" id="charGrid">""" + "".join(f'<div class="char-cell" data-char="{c}" onclick="addChar(\'{c}\')">{c}</div>' for row in GRID for c in row) + """</div>
<button id="clearBtn" onclick="clearInput()">CLEAR INPUT</button>
</div>
<div class="panel" id="info" style="display:none;">
<div class="panel-header">Location Details</div>
<div class="info-grid">
<div class="info-card"><label>Characters Entered</label><div class="value" id="lengthDisplay">0/10</div></div>
<div class="info-card"><label>Latitude</label><div class="value" id="latDisplay">-</div></div>
<div class="info-card"><label>Longitude</label><div class="value" id="lonDisplay">-</div></div>
<div class="info-card"><label>Precision Range</label><div class="value" id="precisionDisplay">-</div></div>
<div class="info-card"><label>Coverage Area</label><div class="value" id="areaDisplay">-</div></div>
</div>
</div>
<div class="panel">
<div class="panel-header">Example Locations</div>
<div class="examples">
<div class="example-btn" onclick="setExample('4P3JK852C9')">Bengaluru MG Road<br><span style="font-size:0.85em;opacity:0.7">4P3-JK8-52C9</span></div>
<div class="example-btn" onclick="setExample('4TF9CP6LK7')">IITNIF<br><span style="font-size:0.85em;opacity:0.7">4TF-9CP-6LK7</span></div>
</div>
</div>
</div>
<div class="map-container">
<div class="map-header">
<div class="map-title">Interactive Location Map</div>
<div class="map-instruction">Hover to explore • Click to select location</div>
</div>
<div id="map"></div>
</div>
</div>
<div class="footer">
<div class="footer-text">© Digital addressing solution for precise location identification. <a href="#">Documentation</a> | <a href="#">API Access</a></div>
</div>
<script>
const map=L.map('map').setView([20.5937,78.9629],5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);
let marker=null,rectangle=null,hoverMarker=null,hoverTimeout=null;
map.on('mousemove',function(e){
clearTimeout(hoverTimeout);
hoverTimeout=setTimeout(()=>{
const lat=e.latlng.lat,lon=e.latlng.lng;
fetch('/encode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat:lat,lon:lon,precision:10})})
.then(r=>r.json()).then(data=>{
if(data.error)return;
if(hoverMarker)map.removeLayer(hoverMarker);
hoverMarker=L.marker([lat,lon],{
icon:L.divIcon({
className:'hover-popup',
html:`<div style="background:rgba(15,23,42,0.95);color:white;padding:10px 14px;border-radius:8px;font-size:11px;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,0.3);white-space:nowrap;font-family:'Courier New',monospace;border:2px solid #dc2626">
<div style="font-size:14px;margin-bottom:4px;letter-spacing:2px">${data.digipin}</div>
<div style="opacity:0.8;font-size:9px;font-weight:400">${lat.toFixed(5)}°N, ${lon.toFixed(5)}°E</div>
</div>`,
iconSize:[140,55],
iconAnchor:[70,55]
})
}).addTo(map);
}).catch(err=>console.error(err))
},80)});
map.on('click',function(e){
const lat=e.latlng.lat,lon=e.latlng.lng;
fetch('/encode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat:lat,lon:lon,precision:10})})
.then(r=>r.json()).then(data=>{
if(data.error){alert('Location outside India bounds');return}
const input=document.getElementById('digipinInput');
input.value=data.digipin;
input.dispatchEvent(new Event('input'));
}).catch(err=>console.error(err))});
function addChar(char){
const input=document.getElementById('digipinInput');
if(input.value.length<10){
input.value+=char;
input.dispatchEvent(new Event('input'));
highlightUsedChars(input.value);
}}
function clearInput(){
const input=document.getElementById('digipinInput');
input.value='';
input.dispatchEvent(new Event('input'));
document.querySelectorAll('.char-cell').forEach(cell=>cell.classList.remove('used'));
document.getElementById('clearBtn').style.display='none';
if(hoverMarker)map.removeLayer(hoverMarker);
}
function highlightUsedChars(value){
document.querySelectorAll('.char-cell').forEach(cell=>cell.classList.remove('used'));
for(let char of value){
const cell=document.querySelector(`.char-cell[data-char="${char}"]`);
if(cell)cell.classList.add('used');
}}
document.getElementById('digipinInput').addEventListener('input',function(){
const value=this.value.toUpperCase().replace(/[^23456789CFJKLMPT]/g,'');
this.value=value;
document.getElementById('clearBtn').style.display=value.length>0?'block':'none';
highlightUsedChars(value);
if(!value.length){document.getElementById('info').style.display='none';if(marker)map.removeLayer(marker);if(rectangle)map.removeLayer(rectangle);map.setView([20.5937,78.9629],5);document.getElementById('progress').style.width='0%';return}
document.getElementById('progress').style.width=(value.length/10*100)+'%';
fetch('/decode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({digipin:value})})
.then(r=>r.json()).then(data=>{if(data.error)return;
document.getElementById('info').style.display='block';
const center=[data.center_lat,data.center_lon];
if(marker)map.removeLayer(marker);
marker=L.marker(center,{
icon:L.icon({
iconUrl:'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
shadowUrl:'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
iconSize:[25,41],
iconAnchor:[12,41],
popupAnchor:[1,-34],
shadowSize:[41,41]
})
}).addTo(map);
marker.bindPopup(`<div style="font-family:sans-serif"><b style="font-size:13px;color:#dc2626">DIGIPIN Location</b><br><span style="font-family:monospace;font-weight:600">${value}</span> (${value.length}/10)<br><small>Lat: ${data.center_lat} | Lon: ${data.center_lon}<br>Precision: ±${data.precision_m}m | Area: ${data.area_km2}km²</small></div>`);
if(rectangle)map.removeLayer(rectangle);
rectangle=L.rectangle([[data.lat_min,data.lon_min],[data.lat_max,data.lon_max]],{color:"#dc2626",weight:2,fillOpacity:0.1}).addTo(map);
map.setView(center,Math.min(18,5+value.length*1.3));
document.getElementById('lengthDisplay').textContent=value.length+'/10';
document.getElementById('latDisplay').textContent=data.center_lat.toFixed(6)+'°';
document.getElementById('lonDisplay').textContent=data.center_lon.toFixed(6)+'°';
document.getElementById('precisionDisplay').textContent='±'+data.precision_m+'m';
document.getElementById('areaDisplay').textContent=data.area_km2+' km²';})});
function setExample(digipin){const input=document.getElementById('digipinInput');input.value='';document.querySelectorAll('.char-cell').forEach(cell=>cell.classList.remove('used'));if(hoverMarker)map.removeLayer(hoverMarker);let i=0;
const interval=setInterval(()=>{if(i<digipin.length){input.value+=digipin[i];input.dispatchEvent(new Event('input'));i++}else clearInterval(interval)},120)}
</script></body></html>"""

@app.route("/encode", methods=["POST"])
def encode():
    try:
        data = request.get_json()
        lat = float(data.get('lat'))
        lon = float(data.get('lon'))
        precision = int(data.get('precision', 10))
        digipin = encode_digipin(lat, lon, precision)
        if digipin:
            return jsonify({"digipin": digipin})
        else:
            return jsonify({"error": "Location outside India"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/decode", methods=["POST"])
def decode():
    try:
        digipin = request.get_json().get('digipin', '').strip()
        if not digipin:
            return jsonify({"error": "Empty DIGIPIN"}), 400
        result = decode_digipin(digipin)
        return jsonify(result) if result else jsonify({"error": "Invalid character"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5050)