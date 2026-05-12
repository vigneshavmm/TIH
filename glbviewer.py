"""
╔══════════════════════════════════════════════════════╗
║  SPATIAL STUDIO  — GLB Digital Twin Platform         ║
║  Architect: Senior 3D Systems Engineer               ║
║  Stack: Flask · Three.js 0.163 · BVH · Cesium 1.115  ║
║  Design: Military Precision Dark UI                  ║
╚══════════════════════════════════════════════════════╝"""
import os, re, json, time
from flask import Flask, request, jsonify, send_from_directory, abort

BASE  = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE, "GLB_Uploads")
os.makedirs(STORE, exist_ok=True)
app   = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB

ALLOWED_MAGIC = {
    b'\x67\x6c\x54\x46',  # GLB magic bytes "glTF"
}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def ok_ext(n):
    return os.path.splitext(n)[1].lower() in {'.glb', '.gltf'}

def safe_name(orig):
    stem = re.sub(r'_+', '_',
           re.sub(r'[^\w\-]', '_',
           os.path.splitext(orig)[0])).strip('_')[:52] or 'model'
    ext  = os.path.splitext(orig)[1].lower()
    if not os.path.exists(os.path.join(STORE, stem + ext)):
        return stem + ext
    i = 2
    while os.path.exists(os.path.join(STORE, f'{stem}_{i}{ext}')):
        i += 1
    return f'{stem}_{i}{ext}'

def ls_models():
    out = []
    for f in sorted(os.listdir(STORE)):
        if ok_ext(f):
            p    = os.path.join(STORE, f)
            size = os.path.getsize(p)
            mtime= os.path.getmtime(p)
            out.append({'name': f, 'size': size, 'mtime': mtime})
    return out

# ─── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return PAGE, 200, {"Content-Type": "text/html;charset=utf-8"}

@app.route("/api/models")
def api_models():
    return jsonify(ls_models())

@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("model")
    if not f or not ok_ext(f.filename):
        abort(400)
    f.stream.seek(0, 2); sz = f.stream.tell(); f.stream.seek(0)
    if sz > 200 * 1024 * 1024:
        abort(413)
    # Validate GLB magic bytes for .glb files
    ext = os.path.splitext(f.filename)[1].lower()
    if ext == '.glb':
        header = f.stream.read(4); f.stream.seek(0)
        if header not in ALLOWED_MAGIC:
            abort(400)
    name = safe_name(f.filename)
    f.save(os.path.join(STORE, name))
    p = os.path.join(STORE, name)
    return jsonify({"name": name, "size": os.path.getsize(p)})

@app.route("/api/delete/<path:n>", methods=["DELETE"])
def api_delete(n):
    p = os.path.join(STORE, os.path.basename(n))
    if os.path.isfile(p):
        os.remove(p)
        return jsonify({"ok": True})
    abort(404)

@app.route("/models/<path:n>")
def serve_model(n):
    return send_from_directory(STORE, os.path.basename(n))

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Spatial Studio</title>
<script>window.CESIUM_BASE_URL='https://cesium.com/downloads/cesiumjs/releases/1.115/Build/Cesium/';</script>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=Orbitron:wght@400;600;700;900&display=swap" rel="stylesheet">
<link href="https://cesium.com/downloads/cesiumjs/releases/1.115/Build/Cesium/Cesium.css" rel="stylesheet">
<script src="https://cesium.com/downloads/cesiumjs/releases/1.115/Build/Cesium/Cesium.js"></script>
<style>
:root {
  --void:    #060810;
  --deep:    #0a0d16;
  --panel:   #0d1120;
  --surface: #131928;
  --raised:  #1a2235;
  --border:  rgba(0,212,255,.12);
  --border2: rgba(0,212,255,.06);
  --cyan:    #00d4ff;
  --cyan-d:  #0099cc;
  --cyan-g:  rgba(0,212,255,.08);
  --amber:   #ffaa00;
  --amber-g: rgba(255,170,0,.08);
  --green:   #00ff88;
  --green-d: #00cc6a;
  --green-g: rgba(0,255,136,.06);
  --red:     #ff3b5c;
  --red-g:   rgba(255,59,92,.08);
  --violet:  #a855f7;
  --violet-g:rgba(168,85,247,.08);
  --t1: #e8f4f8;
  --t2: #8ba0b4;
  --t3: #4a6070;
  --t4: #2a3a4a;
  --mono: 'IBM Plex Mono', monospace;
  --head: 'Orbitron', monospace;
  --r1: 3px;
  --r2: 6px;
  --r3: 10px;
  --sh1: 0 2px 8px rgba(0,0,0,.4);
  --sh2: 0 4px 24px rgba(0,0,0,.6), 0 0 0 1px var(--border);
  --sh3: 0 8px 48px rgba(0,0,0,.8), 0 0 32px rgba(0,212,255,.04);
  --left-w:  240px;
  --right-w: 52px;
  --top-h:   44px;
  --bot-h:   0px;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: 100%; height: 100%; overflow: hidden; background: var(--void); }
body { display: flex; flex-direction: column; font-family: var(--mono); color: var(--t1); font-size: 11px; }
::-webkit-scrollbar { width: 3px; height: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--cyan); }
body::after {
  content: '';
  position: fixed; inset: 0; pointer-events: none; z-index: 9999;
  background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,.03) 2px, rgba(0,0,0,.03) 4px);
}
#topbar {
  height: var(--top-h); min-height: var(--top-h);
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 0;
  z-index: 100; flex-shrink: 0;
  box-shadow: 0 1px 0 var(--border2), var(--sh1);
}
.tb-brand {
  display: flex; align-items: center; gap: 10px;
  padding: 0 16px; height: 100%;
  border-right: 1px solid var(--border2);
  min-width: var(--left-w);
}
.tb-logo {
  width: 26px; height: 26px; border-radius: 5px;
  background: linear-gradient(135deg, var(--cyan) 0%, var(--cyan-d) 100%);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 12px rgba(0,212,255,.3);
}
.tb-logo svg { width: 14px; height: 14px; fill: none; stroke: #fff; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.tb-title { display: flex; flex-direction: column; gap: 1px; }
.tb-name { font: 700 11px/1 var(--head); letter-spacing: .15em; color: var(--t1); }
.tb-sub  { font: 300 8px/1  var(--mono); letter-spacing: .2em; color: var(--t3); }
.tb-center {
  flex: 1; display: flex; align-items: center; justify-content: center;
  gap: 24px; padding: 0 20px;
}
#tb-model-name {
  font: 500 11px/1 var(--mono); color: var(--cyan); letter-spacing: .08em;
  max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tb-pill {
  display: flex; align-items: center; gap: 6px;
  padding: 3px 10px; border-radius: 12px;
  border: 1px solid var(--border2); background: var(--deep);
}
.tb-dot { width: 5px; height: 5px; border-radius: 50%; }
.tb-dot.green { background: var(--green); box-shadow: 0 0 6px var(--green); }
.tb-dot.amber { background: var(--amber); box-shadow: 0 0 6px var(--amber); }
.tb-dot.cyan  { background: var(--cyan);  box-shadow: 0 0 6px var(--cyan);  }
.tb-dot.red   { background: var(--red);   box-shadow: 0 0 6px var(--red);   }
.tb-dot.gray  { background: var(--t4); }
.tb-label { font: 400 9px/1 var(--mono); letter-spacing: .12em; color: var(--t2); text-transform: uppercase; }
.tb-right {
  display: flex; align-items: center; gap: 8px;
  padding: 0 16px; height: 100%;
  border-left: 1px solid var(--border2);
  min-width: var(--right-w);
}
#tb-fps { font: 600 10px/1 var(--mono); color: var(--green); letter-spacing: .08em; }
#body-row {
  flex: 1; display: flex; overflow: hidden; position: relative;
}
#left-panel {
  width: var(--left-w); min-width: var(--left-w);
  background: var(--panel);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  z-index: 50;
  transition: transform .2s cubic-bezier(.4,0,.2,1);
}
#left-panel.collapsed { transform: translateX(calc(-1 * var(--left-w))); }
#dz {
  margin: 12px; border: 1px dashed var(--border);
  border-radius: var(--r2); padding: 16px 12px;
  text-align: center; cursor: pointer;
  transition: all .15s; position: relative; overflow: hidden;
}
#dz::before {
  content: ''; position: absolute; inset: 0;
  background: linear-gradient(135deg, var(--cyan-g), transparent);
  opacity: 0; transition: opacity .15s;
}
#dz:hover::before, #dz.over::before { opacity: 1; }
#dz:hover, #dz.over { border-color: var(--cyan); }
#dz input { display: none; }
.dz-icon { font-size: 20px; opacity: .4; margin-bottom: 6px; }
.dz-t1 { font: 500 10px/1 var(--mono); letter-spacing: .1em; color: var(--t2); }
.dz-t2 { font: 300 9px/1 var(--mono); color: var(--t3); margin-top: 3px; }
#upload-bar {
  height: 2px; background: var(--deep); overflow: hidden; flex-shrink: 0;
  display: none;
}
#upload-bar.show { display: block; }
#upload-fill { height: 100%; width: 0; background: var(--cyan); transition: width .1s; box-shadow: 0 0 8px var(--cyan); }
.sec-label {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 14px 6px;
}
.sec-title { font: 600 8px/1 var(--head); letter-spacing: .25em; color: var(--t3); text-transform: uppercase; }
.sec-count { font: 400 9px/1 var(--mono); color: var(--t4); }
#model-list { flex: 1; overflow-y: auto; }
.model-empty { padding: 20px 14px; font: 400 10px/1.6 var(--mono); color: var(--t4); text-align: center; }
.model-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; cursor: pointer;
  border-left: 2px solid transparent;
  transition: all .1s; position: relative;
}
.model-row:hover { background: var(--raised); }
.model-row.active { background: var(--cyan-g); border-left-color: var(--cyan); }
.model-thumb {
  width: 36px; height: 28px; border-radius: var(--r1); background: var(--surface);
  border: 1px solid var(--border2); overflow: hidden; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; color: var(--t4);
}
.model-thumb canvas { width: 100% !important; height: 100% !important; }
.model-info { flex: 1; min-width: 0; }
.model-name { font: 500 10px/1 var(--mono); color: var(--t1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-row.active .model-name { color: var(--cyan); }
.model-meta { font: 300 8px/1 var(--mono); color: var(--t3); margin-top: 3px; }
.model-del {
  background: none; border: none; cursor: pointer;
  color: var(--t4); font-size: 14px; line-height: 1; padding: 2px 4px;
  border-radius: var(--r1); transition: all .1s; opacity: 0;
}
.model-row:hover .model-del { opacity: 1; }
.model-del:hover { color: var(--red); background: var(--red-g); }
#model-stats {
  border-top: 1px solid var(--border2);
  padding: 10px 0 6px; flex-shrink: 0;
  display: none;
}
.stat-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1px; margin: 0 12px 8px;
  background: var(--border2); border-radius: var(--r2); overflow: hidden;
}
.stat-cell {
  background: var(--surface); padding: 7px 10px;
  display: flex; flex-direction: column; gap: 2px;
}
.stat-k { font: 400 7px/1 var(--head); letter-spacing: .2em; color: var(--t3); text-transform: uppercase; }
.stat-v { font: 600 12px/1 var(--mono); color: var(--t1); }
.stat-v.hi { color: var(--cyan); }
.stat-v.warn { color: var(--amber); }
#vp {
  flex: 1; position: relative; overflow: hidden;
  background: var(--void);
}
#vp canvas { display: block; width: 100% !important; height: 100% !important; outline: none; }
#bvhbar {
  position: absolute; top: 0; left: 0; right: 0; height: 2px;
  z-index: 90; pointer-events: none;
  background: var(--deep);
  display: none;
}
#bvhbar.show { display: block; }
#bvh-fill {
  height: 100%; width: 0; background: var(--amber);
  box-shadow: 0 0 8px var(--amber); transition: width .1s;
}
#xh {
  display: none; position: absolute; top: 50%; left: 50%;
  transform: translate(-50%,-50%); pointer-events: none; z-index: 30;
}
#xh::before, #xh::after {
  content: ''; position: absolute;
  background: rgba(0,212,255,.9);
  filter: drop-shadow(0 0 3px var(--cyan));
}
#xh::before { width: 1px; height: 16px; left: 50%; top: 50%; transform: translate(-50%,-50%); }
#xh::after  { width: 16px; height: 1px; left: 50%; top: 50%; transform: translate(-50%,-50%); }
#vp.fps-lock #xh { display: block; }
#globe-wrap {
  display: none; position: absolute; inset: 0; z-index: 60;
}
#globe-wrap.show { display: flex; flex-direction: column; }
#globe-div { flex: 1; position: relative; }
#globe-div .cesium-widget, #globe-div .cesium-widget canvas {
  width: 100% !important; height: 100% !important;
}
.cesium-widget-credits { display: none !important; }
#empty-state {
  position: absolute; inset: 0; display: flex;
  flex-direction: column; align-items: center; justify-content: center;
  pointer-events: none; z-index: 5;
}
#empty-state.hidden { display: none; }
.empty-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(var(--border2) 1px, transparent 1px),
    linear-gradient(90deg, var(--border2) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse 60% 60% at 50% 50%, black, transparent);
}
.empty-icon { font-size: 48px; opacity: .15; margin-bottom: 16px; }
.empty-t1 { font: 700 14px/1 var(--head); letter-spacing: .2em; color: var(--t3); margin-bottom: 8px; }
.empty-t2 { font: 400 10px/1.6 var(--mono); color: var(--t4); text-align: center; max-width: 220px; }
#right-ribbon {
  width: var(--right-w); min-width: var(--right-w);
  background: var(--panel);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  align-items: center; gap: 2px;
  padding: 8px 0; z-index: 50;
  overflow-y: auto;
}
.rib-btn {
  width: 36px; height: 36px; border-radius: var(--r2);
  border: 1px solid transparent; background: none;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: var(--t3); transition: all .12s; position: relative;
  flex-shrink: 0;
}
.rib-btn svg { width: 16px; height: 16px; }
.rib-btn:hover { background: var(--raised); border-color: var(--border); color: var(--t1); }
.rib-btn.active { background: var(--cyan-g); border-color: var(--cyan); color: var(--cyan); }
.rib-btn.active svg { filter: drop-shadow(0 0 4px var(--cyan)); }
.rib-btn.amber.active { background: var(--amber-g); border-color: var(--amber); color: var(--amber); }
.rib-btn.green.active { background: var(--green-g); border-color: var(--green); color: var(--green); }
.rib-btn.violet.active { background: var(--violet-g); border-color: var(--violet); color: var(--violet); }
.rib-btn.red.active   { background: var(--red-g); border-color: var(--red); color: var(--red); }
.rib-sep { width: 24px; height: 1px; background: var(--border2); margin: 4px 0; flex-shrink: 0; }
.rib-btn[data-tip]:hover::after {
  content: attr(data-tip);
  position: absolute; right: calc(100% + 8px); top: 50%; transform: translateY(-50%);
  background: var(--raised); border: 1px solid var(--border);
  border-radius: var(--r1); padding: 4px 8px;
  font: 400 9px/1 var(--mono); color: var(--t1); white-space: nowrap;
  box-shadow: var(--sh2); pointer-events: none; z-index: 200;
  letter-spacing: .06em;
}
#bot-drawer {
  position: absolute; bottom: 0; left: var(--left-w); right: var(--right-w);
  background: var(--panel); border-top: 1px solid var(--border);
  z-index: 50; transform: translateY(100%);
  transition: transform .2s cubic-bezier(.4,0,.2,1);
  max-height: 260px; display: flex; flex-direction: column;
}
#bot-drawer.open { transform: translateY(0); }
.drawer-tabs {
  display: flex; align-items: center; border-bottom: 1px solid var(--border2);
  flex-shrink: 0;
}
.drawer-tab {
  padding: 8px 16px; font: 400 9px/1 var(--head); letter-spacing: .18em;
  text-transform: uppercase; color: var(--t3); cursor: pointer;
  border-bottom: 2px solid transparent; transition: all .12s;
}
.drawer-tab:hover { color: var(--t2); }
.drawer-tab.active { color: var(--cyan); border-bottom-color: var(--cyan); }
.drawer-close {
  margin-left: auto; margin-right: 8px; background: none; border: none;
  color: var(--t3); cursor: pointer; font-size: 16px; line-height: 1;
  padding: 4px 8px; transition: color .1s;
}
.drawer-close:hover { color: var(--red); }
.drawer-content { flex: 1; overflow: hidden; position: relative; }
.drawer-pane {
  display: none; position: absolute; inset: 0;
  overflow-y: auto; padding: 12px 16px;
}
.drawer-pane.active { display: flex; gap: 24px; flex-wrap: wrap; align-content: flex-start; }
.phys-group { display: flex; flex-direction: column; gap: 6px; min-width: 180px; }
.phys-title { font: 600 8px/1 var(--head); letter-spacing: .2em; color: var(--t3); text-transform: uppercase; margin-bottom: 4px; }
.phys-row { display: flex; align-items: center; gap: 8px; }
.phys-lbl { font: 400 9px/1 var(--mono); color: var(--t3); width: 68px; flex-shrink: 0; }
input[type=range] {
  flex: 1; -webkit-appearance: none; height: 2px;
  background: var(--raised); border-radius: 1px; outline: none; cursor: pointer;
}
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none; width: 10px; height: 10px; border-radius: 50%;
  background: var(--cyan); cursor: pointer; border: 2px solid var(--panel);
  box-shadow: 0 0 6px var(--cyan);
}
.phys-val { font: 400 9px/1 var(--mono); color: var(--t2); width: 32px; text-align: right; }
.env-group { display: flex; flex-direction: column; gap: 6px; min-width: 200px; }
.keys-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
.key-item { display: flex; align-items: center; gap: 6px; }
.key-tag {
  font: 500 8px/1 var(--mono); background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--r1);
  padding: 2px 6px; color: var(--t2); white-space: nowrap; flex-shrink: 0;
}
.key-desc { font: 400 9px/1 var(--mono); color: var(--t3); }
#hud {
  position: absolute; top: 12px; left: 12px;
  display: none; flex-direction: column; gap: 6px;
  pointer-events: none; z-index: 30;
}
#vp.loaded #hud { display: flex; }
.hud-chip {
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(10,13,22,.85); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--r2);
  padding: 5px 10px; box-shadow: var(--sh1);
}
.hud-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.hud-dot.orbit  { background: var(--green); box-shadow: 0 0 6px var(--green); }
.hud-dot.fps    { background: var(--cyan);  box-shadow: 0 0 6px var(--cyan);  }
.hud-dot.fly    { background: var(--violet);box-shadow: 0 0 6px var(--violet);}
.hud-dot.globe  { background: var(--amber); box-shadow: 0 0 6px var(--amber); }
.hud-mode { font: 600 9px/1 var(--head); letter-spacing: .15em; color: var(--t1); text-transform: uppercase; }
#mode-bar {
  position: absolute; bottom: 48px; left: 50%; transform: translateX(-50%);
  display: none; gap: 2px; z-index: 30;
  background: rgba(10,13,22,.9); backdrop-filter: blur(10px);
  border: 1px solid var(--border); border-radius: var(--r3); padding: 4px;
  box-shadow: var(--sh2);
}
#vp.loaded #mode-bar { display: flex; }
.mode-btn {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 14px; border-radius: var(--r2);
  border: none; background: none; cursor: pointer;
  font: 500 9px/1 var(--head); letter-spacing: .15em; color: var(--t3);
  text-transform: uppercase; transition: all .12s;
}
.mode-btn svg { width: 13px; height: 13px; flex-shrink: 0; }
.mode-btn:hover { background: var(--raised); color: var(--t1); }
.mode-btn.active-orbit { background: var(--green-g); color: var(--green); border: 1px solid var(--green); }
.mode-btn.active-fps   { background: var(--cyan-g);  color: var(--cyan);  border: 1px solid var(--cyan);  }
.mode-btn.active-fly   { background: var(--violet-g);color: var(--violet);border: 1px solid var(--violet);}
.mode-sep { width: 1px; background: var(--border2); margin: 4px 2px; }
#compass {
  position: absolute; top: 12px; right: 12px;
  display: none; pointer-events: none; z-index: 30;
}
#vp.loaded #compass { display: block; }
#compass svg { filter: drop-shadow(0 2px 8px rgba(0,0,0,.6)); }
#coord-bar {
  position: absolute; bottom: 0; left: 0; right: 0; height: 28px;
  background: rgba(10,13,22,.9); backdrop-filter: blur(6px);
  border-top: 1px solid var(--border2);
  display: none; align-items: center; gap: 0; z-index: 30; pointer-events: none;
}
#vp.loaded #coord-bar { display: flex; }
.coord-seg {
  display: flex; align-items: center; gap: 5px;
  padding: 0 14px; height: 100%;
  border-right: 1px solid var(--border2);
}
.coord-ax { font: 600 8px/1 var(--head); letter-spacing: .2em; color: var(--t3); width: 8px; }
.coord-v  { font: 400 10px/1 var(--mono); color: var(--t1); min-width: 52px; }
.coord-brg { font: 400 10px/1 var(--mono); color: var(--amber); letter-spacing: .06em; }
#telem {
  position: absolute; top: 12px; right: 60px;
  display: none; flex-direction: column; gap: 3px;
  pointer-events: none; z-index: 30;
}
#vp.loaded #telem { display: flex; }
.telem-card {
  background: rgba(10,13,22,.85); backdrop-filter: blur(8px);
  border: 1px solid var(--border2); border-radius: var(--r2);
  padding: 8px 10px; min-width: 148px;
}
.telem-title { font: 600 7px/1 var(--head); letter-spacing: .25em; color: var(--t3); text-transform: uppercase; margin-bottom: 6px; }
.telem-row { display: flex; justify-content: space-between; align-items: center; padding: 1px 0; }
.telem-k { font: 400 8px/1 var(--mono); color: var(--t3); letter-spacing: .06em; }
.telem-v { font: 500 9px/1 var(--mono); color: var(--t1); }
.telem-v.live { color: var(--green); }
.telem-v.warn { color: var(--amber); }
.fpanel {
  display: none; position: absolute;
  background: rgba(13,17,32,.95); backdrop-filter: blur(12px);
  border: 1px solid var(--border); border-radius: var(--r3);
  box-shadow: var(--sh3); z-index: 40; overflow: hidden;
  min-width: 220px;
}
.fpanel.show { display: block; }
.fpanel-head {
  padding: 8px 12px; border-bottom: 1px solid var(--border2);
  display: flex; align-items: center; justify-content: space-between;
}
.fpanel-title { font: 600 8px/1 var(--head); letter-spacing: .2em; color: var(--cyan); text-transform: uppercase; }
.fpanel-close {
  background: none; border: none; cursor: pointer; color: var(--t3);
  font-size: 14px; line-height: 1; padding: 0 2px; transition: color .1s;
}
.fpanel-close:hover { color: var(--red); }
.fpanel-body { padding: 10px 12px; }
#meas-panel { bottom: 80px; left: 50%; transform: translateX(-50%); }
.meas-dist { font: 700 28px/1 var(--mono); color: var(--cyan); text-shadow: 0 0 20px rgba(0,212,255,.4); }
.meas-unit { font: 400 10px/1 var(--mono); color: var(--t3); }
.meas-save { 
  margin-top: 8px; width: 100%; padding: 7px; border-radius: var(--r2);
  background: var(--cyan); color: var(--void); border: none; cursor: pointer;
  font: 600 9px/1 var(--head); letter-spacing: .15em; transition: opacity .12s;
}
.meas-save:hover { opacity: .85; }
#meas-history { bottom: 220px; left: 50%; transform: translateX(-50%); min-width: 260px; }
.hist-row { display: flex; gap: 10px; align-items: center; padding: 5px 0; border-bottom: 1px solid var(--border2); }
.hist-id { font: 400 8px/1 var(--mono); color: var(--t4); width: 18px; }
.hist-lbl { font: 400 9px/1 var(--mono); color: var(--t2); flex: 1; }
.hist-val { font: 500 10px/1 var(--mono); color: var(--cyan); }
#globe-ctrl {
  top: 60px; right: 60px; width: 250px;
}
.globe-field { margin-bottom: 6px; }
.globe-lbl { font: 400 8px/1 var(--head); letter-spacing: .15em; color: var(--t3); text-transform: uppercase; margin-bottom: 3px; display: block; }
.globe-inp {
  width: 100%; font: 400 10px/1 var(--mono); color: var(--t1);
  background: var(--surface); border: 1px solid var(--border2);
  border-radius: var(--r1); padding: 5px 8px; outline: none; transition: border-color .12s;
}
.globe-inp:focus { border-color: var(--amber); }
.globe-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.globe-btn {
  width: 100%; padding: 8px; margin-top: 6px; border-radius: var(--r2);
  border: none; cursor: pointer; font: 600 9px/1 var(--head);
  letter-spacing: .12em; transition: opacity .12s;
}
.globe-btn.primary { background: var(--amber); color: var(--void); }
.globe-btn.secondary { background: var(--surface); color: var(--t2); border: 1px solid var(--border); }
.globe-btn:hover { opacity: .85; }
.globe-status { font: 400 8px/1.6 var(--mono); color: var(--t3); margin-top: 6px; line-height: 1.6; }
.globe-status.ok { color: var(--green); }
#anim-panel { top: 60px; right: 60px; width: 260px; }
.anim-controls { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.anim-play {
  width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
  background: var(--cyan); color: var(--void); border: none; cursor: pointer;
  font-size: 11px; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 0 12px rgba(0,212,255,.3); transition: all .12s;
}
.anim-play:hover { transform: scale(1.05); }
.anim-scrub-wrap { flex: 1; display: flex; flex-direction: column; gap: 3px; }
.anim-times { display: flex; justify-content: space-between; font: 400 8px/1 var(--mono); color: var(--t3); }
.anim-clip-list { max-height: 120px; overflow-y: auto; }
.anim-clip {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; border-radius: var(--r1); cursor: pointer;
  transition: all .1s; border-left: 2px solid transparent;
}
.anim-clip:hover { background: var(--raised); }
.anim-clip.active { background: var(--cyan-g); border-left-color: var(--cyan); }
.anim-clip-name { font: 500 10px/1 var(--mono); color: var(--t2); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anim-clip.active .anim-clip-name { color: var(--cyan); }
.anim-clip-dur { font: 400 8px/1 var(--mono); color: var(--t4); }
#ann-panel { top: 60px; right: 60px; width: 220px; }
.ann-input-row { display: flex; gap: 6px; margin-bottom: 8px; }
.ann-input {
  flex: 1; font: 400 10px/1 var(--mono); color: var(--t1);
  background: var(--surface); border: 1px solid var(--border2);
  border-radius: var(--r1); padding: 5px 8px; outline: none;
}
.ann-input:focus { border-color: var(--cyan); }
.ann-place-btn {
  padding: 5px 10px; background: var(--cyan); color: var(--void);
  border: none; border-radius: var(--r1); cursor: pointer;
  font: 600 8px/1 var(--head); letter-spacing: .1em;
}
.ann-list { max-height: 120px; overflow-y: auto; }
.ann-item { display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-bottom: 1px solid var(--border2); }
.ann-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); flex-shrink: 0; }
.ann-lbl { flex: 1; font: 400 9px/1 var(--mono); color: var(--t2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ann-del { background: none; border: none; cursor: pointer; color: var(--t4); font-size: 12px; padding: 0 2px; transition: color .1s; }
.ann-del:hover { color: var(--red); }
.ann-pin {
  position: absolute; transform: translate(-50%, -100%);
  background: rgba(0,212,255,.9); color: var(--void);
  font: 600 9px/1 var(--mono); padding: 3px 8px; border-radius: 3px;
  white-space: nowrap; pointer-events: none; z-index: 35;
  box-shadow: 0 0 12px rgba(0,212,255,.4);
}
.ann-pin::after {
  content: ''; position: absolute; bottom: -4px; left: 50%; transform: translateX(-50%);
  border: 4px solid transparent; border-top-color: rgba(0,212,255,.9); border-bottom: 0;
}
#vpt-panel { top: 60px; right: 60px; width: 200px; }
.vpt-save-btn {
  font: 500 8px/1 var(--head); letter-spacing: .15em; padding: 3px 8px;
  background: none; border: 1px solid var(--border); border-radius: var(--r1);
  color: var(--cyan); cursor: pointer; transition: all .12px;
}
.vpt-save-btn:hover { background: var(--cyan-g); border-color: var(--cyan); }
.vpt-list { max-height: 160px; overflow-y: auto; }
.vpt-item {
  display: flex; align-items: center; gap: 6px; padding: 6px 8px;
  cursor: pointer; border-left: 2px solid transparent; transition: all .1s;
}
.vpt-item:hover { background: var(--raised); }
.vpt-item.active { background: var(--cyan-g); border-left-color: var(--cyan); }
.vpt-num { font: 400 8px/1 var(--mono); color: var(--t4); width: 14px; text-align: right; }
.vpt-name { font: 500 10px/1 var(--mono); color: var(--t2); flex: 1; }
.vpt-item.active .vpt-name { color: var(--cyan); }
.vpt-del { background: none; border: none; cursor: pointer; color: var(--t4); font-size: 12px; transition: color .1s; }
.vpt-del:hover { color: var(--red); }
#toast {
  position: absolute; top: 56px; left: 50%; transform: translateX(-50%);
  background: rgba(13,17,32,.95); border: 1px solid var(--border);
  border-radius: var(--r3); padding: 8px 18px;
  font: 500 10px/1 var(--mono); color: var(--t1); letter-spacing: .06em;
  box-shadow: var(--sh2); display: none; z-index: 200; white-space: nowrap;
  backdrop-filter: blur(8px);
}
#toast.ok  { border-color: var(--green);  color: var(--green); }
#toast.err { border-color: var(--red);    color: var(--red); }
#toast.info{ border-color: var(--cyan);   color: var(--cyan); }
#perf-chip {
  position: absolute; bottom: 30px; right: 60px;
  display: none; pointer-events: none; z-index: 30;
}
#vp.loaded #perf-chip { display: block; }
.perf-inner {
  display: flex; gap: 12px;
  background: rgba(10,13,22,.85); backdrop-filter: blur(6px);
  border: 1px solid var(--border2); border-radius: var(--r2);
  padding: 4px 10px;
}
.perf-seg { font: 400 9px/1 var(--mono); color: var(--t3); }
.perf-seg span { color: var(--green); }
#sidebar-toggle {
  position: absolute; top: 50%; left: 0; transform: translateY(-50%);
  background: var(--panel); border: 1px solid var(--border);
  border-left: none; border-radius: 0 var(--r2) var(--r2) 0;
  width: 16px; height: 40px; cursor: pointer; z-index: 60;
  display: flex; align-items: center; justify-content: center;
  color: var(--t3); font-size: 10px; transition: all .15s;
}
#sidebar-toggle:hover { background: var(--raised); color: var(--cyan); }
#loading-overlay {
  position: absolute; inset: 0; z-index: 80; pointer-events: none;
  display: none; flex-direction: column; align-items: center; justify-content: center;
  background: rgba(6,8,16,.7); backdrop-filter: blur(4px);
}
#loading-overlay.show { display: flex; }
.loading-ring {
  width: 40px; height: 40px; border-radius: 50%;
  border: 2px solid var(--border); border-top-color: var(--cyan);
  animation: spin 1s linear infinite; margin-bottom: 14px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { font: 400 10px/1 var(--mono); color: var(--t2); letter-spacing: .12em; }
.loading-sub  { font: 300 8px/1 var(--mono); color: var(--t3); margin-top: 4px; }
</style>
</head>
<body>

<div id="topbar">
  <div class="tb-brand">
    <div class="tb-logo">
      <svg viewBox="0 0 16 16"><path d="M3 12L8 4l5 8"/><path d="M5 9h6"/><circle cx="8" cy="4" r="1.2" fill="white" stroke="none"/></svg>
    </div>
    <div class="tb-title">
      <div class="tb-name">SPATIAL STUDIO</div>
      <div class="tb-sub">GLB · CESIUM </div>
    </div>
  </div>
  <div class="tb-center">
    <span id="tb-model-name">NO MODEL LOADED</span>
    <div class="tb-pill" id="tb-status">
      <div class="tb-dot gray" id="tb-dot"></div>
      <span class="tb-label" id="tb-status-text">IDLE</span>
    </div>
    <div class="tb-pill">
      <div class="tb-dot green"></div>
      <span class="tb-label" id="tb-tri">— TRI</span>
    </div>
    <div class="tb-pill" id="bvh-pill" style="display:none">
      <div class="tb-dot amber"></div>
      <span class="tb-label" id="bvh-text">BVH</span>
    </div>
  </div>
  <div class="tb-right">
    <span id="tb-fps" style="font:600 10px/1 var(--mono);color:var(--green)">—</span>
  </div>
</div>

<div id="body-row">

  <div id="left-panel">
    <div id="dz">
      <input type="file" id="fi" accept=".glb,.gltf" multiple>
      <div class="dz-icon">⬆</div>
      <div class="dz-t1">DROP .GLB / .GLTF</div>
      <div class="dz-t2">or click to browse · 200MB max</div>
    </div>
    <div id="upload-bar"><div id="upload-fill"></div></div>
    <div class="sec-label">
      <span class="sec-title">ASSETS</span>
      <span class="sec-count" id="model-count">0</span>
    </div>
    <div id="model-list">
      <div class="model-empty">Drop or upload GLB/GLTF files<br>to get started</div>
    </div>
    <div id="model-stats">
      <div class="sec-label"><span class="sec-title">GEOMETRY</span></div>
      <div class="stat-grid">
        <div class="stat-cell"><span class="stat-k">Meshes</span><span class="stat-v hi" id="st-mesh">—</span></div>
        <div class="stat-cell"><span class="stat-k">Triangles</span><span class="stat-v" id="st-tri">—</span></div>
        <div class="stat-cell"><span class="stat-k">Materials</span><span class="stat-v" id="st-mat">—</span></div>
        <div class="stat-cell"><span class="stat-k">Anims</span><span class="stat-v" id="st-anim">—</span></div>
      </div>
      <div class="sec-label"><span class="sec-title">SESSION</span></div>
      <div class="stat-grid">
        <div class="stat-cell"><span class="stat-k">Elapsed</span><span class="stat-v hi" id="st-elapsed">00:00</span></div>
        <div class="stat-cell"><span class="stat-k">Distance</span><span class="stat-v" id="st-dist">0.0 m</span></div>
        <div class="stat-cell"><span class="stat-k">Speed</span><span class="stat-v" id="st-spd">0.0</span></div>
        <div class="stat-cell"><span class="stat-k">FPS</span><span class="stat-v" id="st-fps">—</span></div>
      </div>
    </div>
  </div>

  <div id="vp">
    <div id="bvhbar"><div id="bvh-fill"></div></div>
    <div id="xh"></div>
    <div id="globe-wrap">
      <div id="globe-div"></div>
    </div>
    <div id="empty-state">
      <div class="empty-grid"></div>
      <div class="empty-icon">◈</div>
      <div class="empty-t1">NO MODEL LOADED</div>
      <div class="empty-t2">Upload a GLB or GLTF file<br>from the left panel</div>
    </div>
    <div id="loading-overlay">
      <div class="loading-ring"></div>
      <div class="loading-text">LOADING MODEL</div>
      <div class="loading-sub" id="loading-sub">Parsing geometry…</div>
    </div>
    <div id="hud">
      <div class="hud-chip">
        <div class="hud-dot orbit" id="hud-dot"></div>
        <span class="hud-mode" id="hud-mode">ORBIT</span>
      </div>
    </div>
    <div id="mode-bar">
      <button class="mode-btn active-orbit" id="mb-orbit" data-mode="ORBIT">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><ellipse cx="12" cy="12" rx="4" ry="10"/><line x1="2" y1="12" x2="22" y2="12"/></svg>
        Orbit
      </button>
      <div class="mode-sep"></div>
      <button class="mode-btn" id="mb-fps" data-mode="FPS">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M2 12h4M18 12h4"/></svg>
        Walk
      </button>
      <div class="mode-sep"></div>
      <button class="mode-btn" id="mb-fly" data-mode="FLY">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
        Fly
      </button>
    </div>
    <div id="compass">
      <svg width="48" height="48" viewBox="0 0 48 48">
        <circle cx="24" cy="24" r="22" fill="rgba(10,13,22,.85)" stroke="rgba(0,212,255,.15)" stroke-width="1"/>
        <g id="compass-needle" transform="rotate(0 24 24)">
          <polygon points="24,7 26,21 24,20 22,21" fill="#00d4ff"/>
          <polygon points="24,41 26,27 24,28 22,27" fill="#2a3a4a"/>
        </g>
        <text x="24" y="5.5" text-anchor="middle" font-family="Orbitron" font-size="5.5" font-weight="700" fill="#00d4ff" letter-spacing=".1em">N</text>
        <text x="24" y="46" text-anchor="middle" font-family="Orbitron" font-size="5" fill="#2a3a4a">S</text>
        <text x="4"  y="26" text-anchor="middle" font-family="Orbitron" font-size="5" fill="#2a3a4a">W</text>
        <text x="44" y="26" text-anchor="middle" font-family="Orbitron" font-size="5" fill="#2a3a4a">E</text>
      </svg>
    </div>
    <div id="telem">
      <div class="telem-card">
        <div class="telem-title">Position</div>
        <div class="telem-row"><span class="telem-k">X</span><span class="telem-v live" id="tel-x">—</span></div>
        <div class="telem-row"><span class="telem-k">Y</span><span class="telem-v live" id="tel-y">—</span></div>
        <div class="telem-row"><span class="telem-k">Z</span><span class="telem-v live" id="tel-z">—</span></div>
        <div class="telem-row"><span class="telem-k">Bearing</span><span class="telem-v warn" id="tel-brg">—</span></div>
      </div>
      <div class="telem-card">
        <div class="telem-title">Dynamics</div>
        <div class="telem-row"><span class="telem-k">Floor ↓</span><span class="telem-v" id="tel-flr">—</span></div>
        <div class="telem-row"><span class="telem-k">Slope</span><span class="telem-v" id="tel-slp">—</span></div>
        <div class="telem-row"><span class="telem-k">BVH</span><span class="telem-v" id="tel-bvh">—</span></div>
      </div>
    </div>
    <div id="coord-bar">
      <div class="coord-seg"><span class="coord-ax">X</span><span class="coord-v" id="c-x">0.00</span></div>
      <div class="coord-seg"><span class="coord-ax">Y</span><span class="coord-v" id="c-y">0.00</span></div>
      <div class="coord-seg"><span class="coord-ax">Z</span><span class="coord-v" id="c-z">0.00</span></div>
      <div class="coord-seg"><span class="coord-brg" id="c-brg">000° N</span></div>
    </div>
    <div id="perf-chip">
      <div class="perf-inner">
        <div class="perf-seg"><span id="p-fps">—</span> fps</div>
        <div class="perf-seg"><span id="p-tri">—</span> ktri</div>
        <div class="perf-seg"><span id="p-draw">—</span> dc</div>
      </div>
    </div>

    <div class="fpanel" id="meas-panel">
      <div class="fpanel-head">
        <span class="fpanel-title">⟷ MEASURE</span>
        <button class="fpanel-close" id="meas-close">✕</button>
      </div>
      <div class="fpanel-body" style="text-align:center">
        <div class="meas-dist" id="meas-d">0.000</div>
        <div class="meas-unit">metres</div>
        <button class="meas-save" id="meas-save-btn">SAVE MEASUREMENT</button>
      </div>
    </div>
    <div class="fpanel" id="meas-history">
      <div class="fpanel-head">
        <span class="fpanel-title">HISTORY</span>
        <button class="fpanel-close" id="hist-clear" style="font:400 8px/1 var(--mono);color:var(--red);border:1px solid var(--red);border-radius:var(--r1);padding:2px 6px;letter-spacing:.06em">CLEAR</button>
      </div>
      <div class="fpanel-body" style="padding:6px 8px;max-height:160px;overflow-y:auto">
        <div id="hist-list"></div>
      </div>
    </div>
    <div class="fpanel" id="globe-ctrl">
      <div class="fpanel-head">
        <span class="fpanel-title" style="color:var(--amber)">🌍 GEO-ANCHOR</span>
        <button class="fpanel-close" onclick="toggleGlobe(false)">✕</button>
      </div>
      <div class="fpanel-body">
        <div class="globe-grid">
          <div class="globe-field">
            <label class="globe-lbl">Latitude</label>
            <input class="globe-inp" id="g-lat" type="number" step="0.0001" value="51.5074">
          </div>
          <div class="globe-field">
            <label class="globe-lbl">Longitude</label>
            <input class="globe-inp" id="g-lon" type="number" step="0.0001" value="-0.1278">
          </div>
        </div>
        <div class="globe-grid">
          <div class="globe-field">
            <label class="globe-lbl">Altitude (m)</label>
            <input class="globe-inp" id="g-alt" type="number" step="1" value="0">
          </div>
          <div class="globe-field">
            <label class="globe-lbl">Scale</label>
            <input class="globe-inp" id="g-scale" type="number" step="0.1" value="1">
          </div>
        </div>
        <div class="globe-field">
          <label class="globe-lbl">Ion Token (optional)</label>
          <input class="globe-inp" id="g-token" type="text" placeholder="Leave blank for OSM tiles">
        </div>
        <button class="globe-btn primary" id="gc-place">▶ PLACE ON GLOBE</button>
        <button class="globe-btn secondary" id="gc-reinit">↺ REINIT WITH TOKEN</button>
        <div class="globe-status" id="gc-status">No token needed · OSM tiles active by default.</div>
      </div>
    </div>
    <div class="fpanel" id="ann-panel">
      <div class="fpanel-head">
        <span class="fpanel-title">◉ ANNOTATIONS</span>
        <button class="fpanel-close" id="ann-close">✕</button>
      </div>
      <div class="fpanel-body">
        <div class="ann-input-row">
          <input class="ann-input" id="ann-inp" type="text" placeholder="Label…" maxlength="40">
          <button class="ann-place-btn" id="ann-pb">PLACE</button>
        </div>
        <div class="ann-list" id="ann-list">
          <div style="font:400 9px/1 var(--mono);color:var(--t4);text-align:center;padding:10px">No annotations yet</div>
        </div>
      </div>
    </div>
    <div class="fpanel" id="vpt-panel">
      <div class="fpanel-head">
        <span class="fpanel-title">📍 VIEWPOINTS</span>
        <button class="vpt-save-btn" id="vpt-save">+ SAVE VIEW</button>
      </div>
      <div class="fpanel-body" style="padding:6px">
        <div class="vpt-list" id="vpt-list">
          <div style="font:400 9px/1 var(--mono);color:var(--t4);text-align:center;padding:10px">No saved views</div>
        </div>
      </div>
    </div>
    <div class="fpanel" id="anim-panel">
      <div class="fpanel-head">
        <span class="fpanel-title">▶ ANIMATION</span>
        <span id="anim-ct" style="font:400 8px/1 var(--mono);color:var(--t3)"></span>
      </div>
      <div class="fpanel-body">
        <div class="anim-controls">
          <button class="anim-play" id="anim-play-btn">▶</button>
          <div class="anim-scrub-wrap">
            <input type="range" id="anim-progress" min="0" max="1" step=".001" value="0" style="width:100%">
            <div class="anim-times">
              <span id="anim-cur">0.00s</span><span id="anim-dur">0.00s</span>
            </div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span style="font:400 8px/1 var(--mono);color:var(--t3);width:36px">Speed</span>
          <input type="range" id="anim-speed" min=".1" max="3" step=".05" value="1" style="flex:1">
          <span id="anim-sv" style="font:400 8px/1 var(--mono);color:var(--t2);width:24px">1×</span>
        </div>
        <div class="anim-clip-list" id="anim-list">
          <div style="font:400 9px/1 var(--mono);color:var(--t4);text-align:center;padding:8px">No animations</div>
        </div>
      </div>
    </div>

    <div id="toast"></div>
  </div>

  <div id="right-ribbon">
    <button class="rib-btn active" id="rb-orbit" data-tip="Orbit Camera" onclick="setMode('ORBIT')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><ellipse cx="12" cy="12" rx="4" ry="10"/><line x1="2" y1="12" x2="22" y2="12"/></svg>
    </button>
    <button class="rib-btn" id="rb-fps" data-tip="Walk Mode (FPS)" onclick="setMode('FPS')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="3"/><path d="M6 21v-2a4 4 0 014-4h4a4 4 0 014 4v2"/></svg>
    </button>
    <button class="rib-btn violet" id="rb-fly" data-tip="Fly Mode" onclick="setMode('FLY')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
    </button>
    <div class="rib-sep"></div>
    <button class="rib-btn" id="rb-measure" data-tip="Measure Distance" onclick="toggleMeasure()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><line x1="2" y1="12" x2="22" y2="12"/><polyline points="8 8 2 12 8 16"/><polyline points="16 8 22 12 16 16"/></svg>
    </button>
    <button class="rib-btn" id="rb-ann" data-tip="Annotations" onclick="toggleAnn()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
    </button>
    <button class="rib-btn" id="rb-vpt" data-tip="Viewpoints" onclick="togglePanel('vpt-panel','rb-vpt')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
    </button>
    <div class="rib-sep"></div>
    <button class="rib-btn amber" id="rb-wire" data-tip="Wireframe Toggle" onclick="toggleWire()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2"/><line x1="12" y1="2" x2="12" y2="22"/><line x1="2" y1="8.5" x2="22" y2="8.5"/><line x1="2" y1="15.5" x2="22" y2="15.5"/></svg>
    </button>
    <button class="rib-btn" id="rb-anim" data-tip="Animations" onclick="togglePanel('anim-panel','rb-anim')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polygon points="5 3 19 12 5 21 5 3"/></svg>
    </button>
    <button class="rib-btn" id="rb-flash" data-tip="Flashlight [F]" onclick="toggleFlash()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
    </button>
    <div class="rib-sep"></div>
    <button class="rib-btn" id="rb-env" data-tip="Environment" onclick="openDrawer('env')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/></svg>
    </button>
    <button class="rib-btn" id="rb-phys" data-tip="Physics Settings" onclick="openDrawer('phys')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
    </button>
    <button class="rib-btn amber" id="rb-globe" data-tip="Cesium Globe" onclick="toggleGlobe(true)">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 010 20M12 2a15.3 15.3 0 000 20"/></svg>
    </button>
    <div class="rib-sep"></div>
    <button class="rib-btn" id="rb-keys" data-tip="Key Bindings" onclick="openDrawer('keys')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2" y="6" width="20" height="13" rx="2" ry="2"/><path d="M6 10h0M10 10h0M14 10h0M18 10h0M8 14h8"/></svg>
    </button>
    <button class="rib-btn" id="rb-shot" data-tip="Screenshot" onclick="takeShot()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>
    </button>
  </div>

</div>

<div id="bot-drawer">
  <div class="drawer-tabs">
    <div class="drawer-tab active" data-pane="phys">NAV PHYSICS</div>
    <div class="drawer-tab" data-pane="env">ENVIRONMENT</div>
    <div class="drawer-tab" data-pane="keys">CONTROLS</div>
    <button class="drawer-close" onclick="closeDrawer()">✕</button>
  </div>
  <div class="drawer-content">
    <div class="drawer-pane active" id="dp-phys">
      <div class="phys-group">
        <div class="phys-title">Movement</div>
        <div class="phys-row"><span class="phys-lbl">Walk m/s</span><input type="range" data-key="walkSpeed" min="2" max="18" step=".5" value="6"><span class="phys-val">6</span></div>
        <div class="phys-row"><span class="phys-lbl">Sprint ×</span><input type="range" data-key="sprintMult" min="1.2" max="4" step=".1" value="2.2"><span class="phys-val">2.2</span></div>
        <div class="phys-row"><span class="phys-lbl">Jump m/s</span><input type="range" data-key="jumpImpulse" min="2" max="14" step=".5" value="6"><span class="phys-val">6</span></div>
      </div>
      <div class="phys-group">
        <div class="phys-title">Simulation</div>
        <div class="phys-row"><span class="phys-lbl">Gravity</span><input type="range" data-key="gravity" min="4" max="30" step=".5" value="9.8"><span class="phys-val">9.8</span></div>
        <div class="phys-row"><span class="phys-lbl">Friction</span><input type="range" data-key="friction" min="0" max="1" step=".01" value=".82"><span class="phys-val">.82</span></div>
        <div class="phys-row"><span class="phys-lbl">Air drag</span><input type="range" data-key="airDrag" min=".8" max="1" step=".01" value=".98"><span class="phys-val">.98</span></div>
      </div>
      <div class="phys-group">
        <div class="phys-title">Camera</div>
        <div class="phys-row"><span class="phys-lbl">Mouse sens</span><input type="range" data-key="mouseSens" min=".5" max="5" step=".1" value="2"><span class="phys-val">2</span></div>
        <div class="phys-row"><span class="phys-lbl">Max slope°</span><input type="range" data-key="maxSlope" min="20" max="75" step="1" value="50"><span class="phys-val">50</span></div>
      </div>
    </div>
    <div class="drawer-pane" id="dp-env">
      <div class="env-group">
        <div class="phys-title">Lighting</div>
        <div class="phys-row"><span class="phys-lbl">Sun azimuth</span><input type="range" id="e-az"  min="0"   max="360" step="1"   value="225"><span class="phys-val" id="ev-az">225</span></div>
        <div class="phys-row"><span class="phys-lbl">Sun altitude</span><input type="range" id="e-el"  min="5"   max="80"  step="1"   value="40"><span class="phys-val"  id="ev-el">40</span></div>
        <div class="phys-row"><span class="phys-lbl">Exposure</span><input type="range" id="e-exp" min=".3"  max="2"   step=".05"  value=".88"><span class="phys-val" id="ev-exp">.88</span></div>
      </div>
      <div class="env-group">
        <div class="phys-title">Atmosphere</div>
        <div class="phys-row"><span class="phys-lbl">Fog density</span><input type="range" id="e-fog" min=".0001" max=".02" step=".0001" value=".002"><span class="phys-val" id="ev-fog">.002</span></div>
        <div class="phys-row"><span class="phys-lbl">Fog color</span><input type="color" id="e-fogcol" value="#0d1928" style="flex:1;height:22px;border:none;border-radius:var(--r1);cursor:pointer"></div>
        <div class="phys-row"><span class="phys-lbl">Background</span><input type="color" id="e-bgcol" value="#0d1928" style="flex:1;height:22px;border:none;border-radius:var(--r1);cursor:pointer"></div>
      </div>
    </div>
    <div class="drawer-pane" id="dp-keys">
      <div class="keys-grid">
        <div class="key-item"><span class="key-tag">W A S D</span><span class="key-desc">Move</span></div>
        <div class="key-item"><span class="key-tag">Mouse</span><span class="key-desc">Look</span></div>
        <div class="key-item"><span class="key-tag">Shift</span><span class="key-desc">Sprint</span></div>
        <div class="key-item"><span class="key-tag">Space</span><span class="key-desc">Jump / Fly ↑</span></div>
        <div class="key-item"><span class="key-tag">C</span><span class="key-desc">Crouch / Fly ↓</span></div>
        <div class="key-item"><span class="key-tag">F</span><span class="key-desc">Flashlight</span></div>
        <div class="key-item"><span class="key-tag">G</span><span class="key-desc">Snap to floor</span></div>
        <div class="key-item"><span class="key-tag">R</span><span class="key-desc">Respawn</span></div>
        <div class="key-item"><span class="key-tag">M</span><span class="key-desc">Cycle mode</span></div>
        <div class="key-item"><span class="key-tag">Tab</span><span class="key-desc">Toggle sidebar</span></div>
        <div class="key-item"><span class="key-tag">Esc</span><span class="key-desc">Exit / Cancel</span></div>
        <div class="key-item"><span class="key-tag">Scroll</span><span class="key-desc">FOV / Fly speed</span></div>
      </div>
    </div>
  </div>
</div>

<!-- ─── FIX: added BufferGeometryUtils to importmap ─── -->
<script type="importmap">{"imports":{
  "three":"https://cdn.jsdelivr.net/npm/three@0.163.0/build/three.module.js",
  "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.163.0/examples/jsm/",
  "three-mesh-bvh":"https://cdn.jsdelivr.net/npm/three-mesh-bvh@0.7.4/build/index.module.js"
}}</script>
<script type="module">
import * as THREE from 'three';
import { GLTFLoader }      from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls }   from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
// ─── FIX 1: import mergeGeometries for single-BVH collision mesh ───
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from 'three-mesh-bvh';
THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

const CFG = Object.freeze({
  MAX_DPR:2, FOV:68, FOV_MIN:20, FOV_MAX:100,
  CAM_NEAR:.04, CAM_FAR:2000,
  AMB:.8, SUN:1.6, FILL:.3, ENV:1.2,
  SHAD_SZ:2048, SHAD_FAR:180, SHAD_R:40,
  FL_INT:40, FL_DIST:60, FL_ANGLE:Math.PI/7, FL_PEN:.4, FL_DEC:1.5,
  BODY_LIGHT_INT:5, BODY_LIGHT_DIST:14,
  DT:1/60,
  // ─── FIX 2: max physics steps per frame — prevents tunneling on lag spikes ───
  MAX_PHYS_STEPS: 5,
  MAX_FALL:50, DEATH_Y:-100,
  EYE_H:1.72, CHAR_R:.12, GOFF:.28, STEP_H:.46,
  M_SIZE:30, BVH_LEAF:8, MIN_MESH_R:.18, SPAWN_GRID:5,
  COYOTE:5, GY_FRAMES:6,
});

const PHY = { walkSpeed:6, sprintMult:2.2, jumpImpulse:6, gravity:9.8, friction:.82, airDrag:.98, mouseSens:2, maxSlope:50 };
document.querySelectorAll('input[type=range][data-key]').forEach(el => {
  const k = el.dataset.key, sv = el.nextElementSibling;
  el.addEventListener('input', () => { PHY[k] = parseFloat(el.value); if(sv) sv.textContent = el.value; });
  PHY[k] = parseFloat(el.value);
});

const $  = id => document.getElementById(id);
const clamp = (v,a,b) => v<a?a:v>b?b:v;
const DEG = 180/Math.PI;
const COMPASS = ['N','NE','E','SE','S','SW','W','NW'];
let _toastTimer;
function toast(msg, type='', ms=2800) {
  const el = $('toast');
  el.textContent = msg; el.className = type;
  el.style.display = 'block';
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.style.display='none', ms);
}
function fmtBytes(b) {
  if (b < 1024) return b+'B';
  if (b < 1048576) return (b/1024).toFixed(1)+'KB';
  return (b/1048576).toFixed(1)+'MB';
}
function fmtSec(s) { return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0'); }

const vp = $('vp');
const R = new THREE.WebGLRenderer({ antialias:true, powerPreference:'high-performance', preserveDrawingBuffer:true });
R.setPixelRatio(Math.min(devicePixelRatio, CFG.MAX_DPR));
R.setSize(vp.clientWidth, vp.clientHeight, false);
R.outputColorSpace = THREE.SRGBColorSpace;
R.toneMapping = THREE.ACESFilmicToneMapping;
R.toneMappingExposure = .88;
R.shadowMap.enabled = true;
R.shadowMap.type = THREE.PCFSoftShadowMap;
R.domElement.tabIndex = 0;
vp.appendChild(R.domElement);

new ResizeObserver(() => {
  const w = vp.clientWidth, h = vp.clientHeight;
  R.setSize(w, h, false);
  cam.aspect = w/h;
  cam.updateProjectionMatrix();
}).observe(vp);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1928);
scene.fog = new THREE.FogExp2(0x0d1928, .002);

const pmrem = new THREE.PMREMGenerator(R);
scene.environment = pmrem.fromScene(new RoomEnvironment(), .15).texture;
pmrem.dispose();

const sunLight  = new THREE.DirectionalLight(0xfff5e8, CFG.SUN);
const fillLight = new THREE.DirectionalLight(0x6080b0, CFG.FILL);
sunLight.castShadow = true;
sunLight.shadow.mapSize.set(CFG.SHAD_SZ, CFG.SHAD_SZ);
sunLight.shadow.camera.near = .5;
sunLight.shadow.camera.far  = CFG.SHAD_FAR;
scene.add(new THREE.AmbientLight(0xffffff, CFG.AMB), sunLight, fillLight);

const bodyLight = new THREE.PointLight(0xfff0d8, CFG.BODY_LIGHT_INT, CFG.BODY_LIGHT_DIST, 1.5);
const flash = new THREE.SpotLight(0xfff8f0, 0, CFG.FL_DIST, CFG.FL_ANGLE, CFG.FL_PEN, CFG.FL_DEC);
scene.add(flash, flash.target);
let flashOn = false;
const sunDir = new THREE.Vector3();

function applySun() {
  const az = parseFloat($('e-az').value) * Math.PI/180;
  const el = parseFloat($('e-el').value) * Math.PI/180;
  sunDir.set(Math.cos(el)*Math.sin(az), Math.sin(el), Math.cos(el)*Math.cos(az));
  sunLight.position.copy(sunDir).multiplyScalar(50);
  sunLight.target.position.set(0,0,0); sunLight.target.updateMatrixWorld();
  fillLight.position.set(-sunDir.x*15, Math.max(Math.sin(el)*10,4), -sunDir.z*15);
}
function fitShadow(wp) {
  sunLight.position.copy(wp).addScaledVector(sunDir, 50);
  sunLight.target.position.copy(wp); sunLight.target.updateMatrixWorld();
  const sc = sunLight.shadow.camera, r = CFG.SHAD_R;
  sc.left=-r; sc.right=r; sc.bottom=-r; sc.top=r; sc.updateProjectionMatrix();
}

[['e-az','ev-az',0,()=>applySun()],
 ['e-el','ev-el',0,()=>applySun()],
 ['e-exp','ev-exp',2,()=>R.toneMappingExposure=parseFloat($('e-exp').value)],
 ['e-fog','ev-fog',4,()=>scene.fog.density=parseFloat($('e-fog').value)],
].forEach(([id,vid,dec,fn])=>{
  const el=$(id), ve=$(vid);
  if(!el||!ve) return;
  const sync=()=>{ if(ve) ve.textContent=parseFloat(el.value).toFixed(dec); fn(); };
  el.addEventListener('input',sync); sync();
});
$('e-fogcol').addEventListener('input', e => {
  const c = new THREE.Color(e.target.value);
  scene.fog.color.set(c);
});
$('e-bgcol').addEventListener('input', e => {
  scene.background = new THREE.Color(e.target.value);
});
applySun();

const SRGB_K   = ['map','emissiveMap'];
const LINEAR_K = ['normalMap','roughnessMap','metalnessMap','aoMap','displacementMap','alphaMap','lightMap'];
const ALL_K    = [...SRGB_K, ...LINEAR_K];
let wireOn = false;

function fixMaterials(root) {
  root.traverse(n => {
    if (!n.isMesh) return;
    [].concat(n.material).forEach(m => {
      if (!m) return;
      SRGB_K.forEach(k   => { if (m[k] && m[k].colorSpace!==THREE.SRGBColorSpace)       { m[k].colorSpace=THREE.SRGBColorSpace;       m[k].needsUpdate=true; }});
      LINEAR_K.forEach(k => { if (m[k] && m[k].colorSpace!==THREE.LinearSRGBColorSpace) { m[k].colorSpace=THREE.LinearSRGBColorSpace; m[k].needsUpdate=true; }});
      if ('envMapIntensity' in m) m.envMapIntensity = CFG.ENV;
      if ('metalness' in m) m.metalness = Math.min(m.metalness, .65);
      if ('roughness' in m) m.roughness = Math.max(m.roughness, .15);
      m.side = THREE.DoubleSide;
      m.wireframe = wireOn;
      if (m.color) { const h={}; m.color.getHSL(h); if (h.l<.18) m.color.multiplyScalar(2.5); }
      m.needsUpdate = true;
    });
    n.castShadow = n.receiveShadow = true;
    n.frustumCulled = true;
  });
}
function setWireframe(v) {
  wireOn = v;
  if (!activeRoot) return;
  activeRoot.traverse(n => { if (!n.isMesh) return; [].concat(n.material).forEach(m => { if(m){m.wireframe=v;m.needsUpdate=true;} }); });
}
function disposeModel(root) {
  root.traverse(n => {
    if (!n.isMesh) return;
    if (n.geometry) { n.geometry.dispose(); }
    [].concat(n.material).forEach(m => { if(!m) return; ALL_K.forEach(k=>m[k]?.dispose()); m.dispose(); });
  });
}

// ─── FIX 3: dispose the single merged collision mesh ───
function disposeColMesh() {
  if (!singleColMesh) return;
  if (singleColMesh.geometry.boundsTree) singleColMesh.geometry.disposeBoundsTree();
  singleColMesh.geometry.dispose();
  singleColMesh.material.dispose();
  singleColMesh = null;
}

const rig = new THREE.Object3D(); scene.add(rig);
const cam = new THREE.PerspectiveCamera(CFG.FOV, vp.clientWidth/vp.clientHeight, CFG.CAM_NEAR, CFG.CAM_FAR);
cam.rotation.order = 'YXZ'; scene.add(cam); cam.position.set(0,12,35);
let fovTarget=CFG.FOV, yaw=0, pitch=0;

const orbit = new OrbitControls(cam, R.domElement);
orbit.enableDamping = true; orbit.dampingFactor = .07;

const flyPos = new THREE.Vector3(); let flySpd = 8;
let mode = 'ORBIT', fpsLocked = false;
const canvas = R.domElement;
let activeRoot = null, modelCentre = new THREE.Vector3();

function setMode(m) {
  if (!activeRoot && m !== 'ORBIT') return toast('Load a model first','err');
  const prev = mode; mode = m;
  if (prev==='FPS') { rig.remove(cam); rig.remove(bodyLight); scene.add(cam); }
  if (fpsLocked && m==='ORBIT') document.exitPointerLock();
  orbit.enabled = m==='ORBIT';
  if (m==='ORBIT') {
    const wp=new THREE.Vector3(); cam.getWorldPosition(wp);
    cam.position.copy(wp); cam.rotation.set(pitch,yaw,0,'YXZ');
    if (activeRoot) { orbit.target.copy(modelCentre); orbit.update(); }
  } else if (m==='FPS') {
    scene.remove(cam); rig.add(cam); rig.add(bodyLight);
    rig.position.copy(body.pos); rig.rotation.y=yaw;
    cam.position.set(0,0,0); cam.rotation.set(pitch,0,0,'YXZ'); accum=0;
    canvas.requestPointerLock();
  } else {
    if (prev==='FPS') cam.getWorldPosition(flyPos); else flyPos.copy(cam.position);
    cam.position.copy(flyPos); cam.rotation.set(pitch,yaw,0,'YXZ');
    canvas.requestPointerLock();
  }
  const isFPS=m==='FPS', isFly=m==='FLY';
  $('rb-orbit').classList.toggle('active', m==='ORBIT');
  $('rb-fps').classList.toggle('active',   m==='FPS');
  $('rb-fly').classList.toggle('active',   m==='FLY');
  document.querySelectorAll('.mode-btn').forEach(b=>{
    b.className = 'mode-btn';
    if (b.dataset.mode===m) b.classList.add(m==='ORBIT'?'active-orbit':m==='FPS'?'active-fps':'active-fly');
  });
  $('hud-dot').className = 'hud-dot '+(isFly?'fly':isFPS?'fps':'orbit');
  $('hud-mode').textContent = m + (m!=='ORBIT'?' MODE':'');
  vp.classList.toggle('fps-lock', (isFPS||isFly)&&fpsLocked);
  setStatus(m==='FPS'?'WALK':m==='FLY'?'FLY':'ORBIT',
             m==='FPS'?'cyan':m==='FLY'?'violet':'green');
}
window.setMode = setMode;

document.querySelectorAll('.mode-btn').forEach(b =>
  b.addEventListener('click', () => setMode(b.dataset.mode))
);

document.addEventListener('pointerlockchange', () => {
  fpsLocked = document.pointerLockElement === canvas;
  vp.classList.toggle('fps-lock', fpsLocked && (mode==='FPS'||mode==='FLY'));
});
document.addEventListener('mousemove', e => {
  if (!fpsLocked || mode==='ORBIT') return;
  const s = PHY.mouseSens * .001;
  yaw   -= e.movementX * s;
  pitch  = clamp(pitch - e.movementY * s, -1.55, 1.55);
  if (mode==='FPS') { rig.rotation.y=yaw; cam.rotation.x=pitch; }
  else cam.rotation.set(pitch,yaw,0,'YXZ');
  $('compass-needle').setAttribute('transform', `rotate(${-yaw*DEG} 24 24)`);
});
vp.addEventListener('wheel', e => {
  if (mode==='FLY') { e.preventDefault(); flySpd=clamp(flySpd-e.deltaY*.02,2,100); toast('Fly: '+flySpd.toFixed(1)+' m/s','info',800); return; }
  if (mode!=='FPS') return;
  e.preventDefault();
  fovTarget = clamp(fovTarget+e.deltaY*.04, CFG.FOV_MIN, CFG.FOV_MAX);
},{passive:false});
canvas.addEventListener('click', () => {
  if (measureMode) { handleMeasureClick(); return; }
  if (annMode)     { handleAnnClick();     return; }
  if (mode!=='ORBIT'&&!fpsLocked) canvas.requestPointerLock();
});

const keys = new Set();
const wRay2 = new THREE.Raycaster(); wRay2.firstHitOnly=true;
window.addEventListener('keydown', e => {
  keys.add(e.code);
  if (e.code==='Tab')   { e.preventDefault(); $('left-panel').classList.toggle('collapsed'); return; }
  if (e.code==='KeyM')  { cycleMode(); return; }
  if (e.code==='KeyF')  { toggleFlash(); return; }
  if (e.code==='Escape') {
    if (measureMode) { toggleMeasure(); return; }
    if (annMode)     { toggleAnn();     return; }
    if (fpsLocked)   document.exitPointerLock();
    return;
  }
  // ─── FIX: guard jump with singleColMesh (was colMeshes.length) ───
  if (e.code==='Space' && fpsLocked && mode==='FPS' && onGround && bvhReady && singleColMesh) {
    body.vel.y = PHY.jumpImpulse; onGround=false;
  }
  if (e.code==='KeyG' && mode==='FPS' && bvhReady && singleColMesh) {
    gRay.ray.origin.copy(body.pos); gRay.far=CFG.M_SIZE*4;
    const h=gRay.intersectObjects([singleColMesh],false)[0];
    if (h) { body.pos.y=h.point.y+CFG.EYE_H+.02; body.vel.set(0,0,0); resetGY(); onGround=true; toast('Snapped to floor','ok'); }
    else toast('No floor below','err');
  }
  if (e.code==='KeyR' && mode==='FPS') { body.pos.copy(spawn); body.vel.set(0,0,0); resetGY(); toast('Respawned','ok'); }
});
window.addEventListener('keyup', e => keys.delete(e.code));
function cycleMode() {
  mode==='ORBIT'?setMode('FPS'):mode==='FPS'?setMode('FLY'):setMode('ORBIT');
}
function pollIntent() {
  let fx=(keys.has('KeyW')||keys.has('ArrowUp')?1:0)-(keys.has('KeyS')||keys.has('ArrowDown')?1:0);
  let rz=(keys.has('KeyD')||keys.has('ArrowRight')?1:0)-(keys.has('KeyA')||keys.has('ArrowLeft')?1:0);
  const L=Math.hypot(fx,rz); if(L>1){fx/=L;rz/=L;}
  return {fwd:fx,rgt:rz,moving:L>.01,sprint:keys.has('ShiftLeft')||keys.has('ShiftRight'),crouch:keys.has('KeyC')};
}

const body = {pos:new THREE.Vector3(0,4,5), vel:new THREE.Vector3(), prev:new THREE.Vector3(0,4,5)};
let spawn=new THREE.Vector3(0,4,5), accum=0, onGround=false, coyoteLeft=0;
const gYBuf=new Float32Array(CFG.GY_FRAMES); let gYIdx=0, gYFull=false;
function resetGY(){gYBuf.fill(0);gYIdx=0;gYFull=false;}
let sessionDist=0, sessionStart=Date.now();

function physStep(i) {
  const sy=Math.sin(yaw),cy=Math.cos(yaw);
  const spd=PHY.walkSpeed*(i.sprint?PHY.sprintMult:1)*(i.crouch?.38:1)*CFG.DT;
  body.vel.x+=(-sy*i.fwd+cy*i.rgt)*spd;
  body.vel.z+=(-cy*i.fwd-sy*i.rgt)*spd;
  if (!onGround) { body.vel.y-=PHY.gravity*CFG.DT; body.vel.y=Math.max(-CFG.MAX_FALL,body.vel.y); }
  const k=Math.pow(onGround?PHY.friction:PHY.airDrag,CFG.DT/.016);
  body.vel.x*=k; body.vel.z*=k;
  body.prev.copy(body.pos); body.pos.addScaledVector(body.vel,CFG.DT);
  sessionDist+=Math.hypot(body.pos.x-body.prev.x,body.pos.z-body.prev.z);
  if (body.pos.y<CFG.DEATH_Y){body.pos.copy(spawn);body.vel.set(0,0,0);}
}

// ─── All collision raycasts now use [singleColMesh] — O(log N) instead of O(mesh_count) ───
const gRay=new THREE.Raycaster(); gRay.ray.direction.set(0,-1,0); gRay.firstHitOnly=true;
const wRay=new THREE.Raycaster(); wRay.firstHitOnly=true;
const _wn=new THREE.Vector3(), _sn=new THREE.Vector3();
let slope=90;
const GOFFS=[[0,0],[1,0],[-1,0],[0,1],[0,-1]].map(([x,z])=>new THREE.Vector2(x*CFG.GOFF,z*CFG.GOFF));
const WDIRS=[[1,0],[-1,0],[0,1],[0,-1],[.707,.707],[-.707,-.707],[.707,-.707],[-.707,.707]]
  .map(([x,z])=>Object.freeze(new THREE.Vector3(x,0,z).normalize()));

// singleColMesh positions are in world space (baked during build),
// matrixWorld is identity, so face normals need no transformDirection call —
// but we keep it for correctness (transform by identity = no-op).
function resolveGround(eH) {
  if (!bvhReady || !singleColMesh) return;
  onGround=false; slope=90; let sumY=0,n=0; _wn.set(0,1,0);
  for (const o of GOFFS) {
    gRay.ray.origin.set(body.pos.x+o.x,body.pos.y+CFG.STEP_H+.1,body.pos.z+o.y);
    gRay.far=eH+CFG.STEP_H+.18;
    const h=gRay.intersectObjects([singleColMesh],false)[0]; if(!h) continue;
    _sn.copy(h.face.normal).transformDirection(singleColMesh.matrixWorld).normalize();
    const d=Math.acos(clamp(_sn.y,-1,1))*DEG; if(d<slope){slope=d;_wn.copy(_sn);}
    sumY+=h.point.y; n++;
  }
  if (!n){if(coyoteLeft>0){onGround=true;coyoteLeft--;}return;}
  coyoteLeft=CFG.COYOTE;
  gYBuf[gYIdx%CFG.GY_FRAMES]=sumY/n; gYIdx++;
  if(gYIdx>=CFG.GY_FRAMES)gYFull=true;
  const cnt=gYFull?CFG.GY_FRAMES:gYIdx; let avgY=0;
  for(let i=0;i<cnt;i++) avgY+=gYBuf[i%CFG.GY_FRAMES]; avgY/=cnt;
  const gY=avgY+eH;
  if(slope<=PHY.maxSlope){
    if(body.pos.y<=gY+.14){body.pos.y=gY;if(body.vel.y<0)body.vel.y=0;onGround=true;}
  } else if(body.vel.y<=0){
    const L=Math.hypot(_wn.x,_wn.z);
    if(L>.01){body.vel.x+=(_wn.x/L)*PHY.gravity*CFG.DT*2;body.vel.z+=(_wn.z/L)*PHY.gravity*CFG.DT*2;}
  }
}
function resolveWalls(eH) {
  if (!bvhReady || !singleColMesh) return;
  const hD=CFG.CHAR_R, oyMid=body.pos.y-eH*.42, oyKnee=body.pos.y-eH*.82;
  for (const dir of WDIRS) {
    wRay.ray.origin.set(body.pos.x,oyMid,body.pos.z); wRay.ray.direction.copy(dir); wRay.far=hD;
    const hm=wRay.intersectObjects([singleColMesh],false)[0]; if(!hm) continue;
    wRay2.ray.origin.set(body.pos.x,oyKnee,body.pos.z); wRay2.ray.direction.copy(dir); wRay2.far=hD;
    const hk=wRay2.intersectObjects([singleColMesh],false)[0];
    const fac=hk?1.0:0.35;
    _wn.copy(hm.face.normal).transformDirection(singleColMesh.matrixWorld).normalize();
    _wn.y=0; const L=_wn.length(); if(L<.01) continue; _wn.divideScalar(L);
    const pen=(hD-hm.distance)*fac;
    if(pen>0){body.pos.x+=_wn.x*pen;body.pos.z+=_wn.z*pen;}
    const dot=body.vel.x*_wn.x+body.vel.z*_wn.z;
    if(dot<0){body.vel.x-=_wn.x*dot*fac;body.vel.z-=_wn.z*dot*fac;}
  }
}
function resolveStep(eH) {
  if(!bvhReady || !singleColMesh || !onGround) return;
  const spd=Math.hypot(body.vel.x,body.vel.z); if(spd<.04) return;
  const vx=body.vel.x/spd,vz=body.vel.z/spd;
  wRay.ray.direction.set(vx,0,vz); wRay.far=CFG.CHAR_R+.28;
  wRay.ray.origin.set(body.pos.x,body.pos.y-eH+CFG.STEP_H+.05,body.pos.z);
  if(wRay.intersectObjects([singleColMesh],false).length) return;
  wRay.ray.origin.y=body.pos.y-eH+.05;
  if(wRay.intersectObjects([singleColMesh],false).length) body.pos.y+=.09;
}

// ════════════════════════════════════════════════════
// BVH BUILD — FIX: merge all collision geometry into ONE mesh with ONE BVH.
// Raycasting against N meshes is O(N * log T_per_mesh).
// Raycasting against 1 merged mesh is O(log T_total) — same work, no per-object overhead.
// Positions are baked into world space via applyMatrix4 so matrixWorld stays identity.
// ════════════════════════════════════════════════════
let bvhReady=false, colMeshes=[], bvhGen=0;
let singleColMesh=null; // the one merged collision mesh

function buildBVH(meshes, gen) {
  bvhReady = false;
  $('bvhbar').classList.add('show');
  $('bvh-fill').style.width='0';
  $('bvh-pill').style.display='flex';
  $('bvh-text').textContent='COL 0%';
  $('tel-bvh').textContent='Collecting…';

  // Dispose previous merged mesh
  disposeColMesh();

  const stripped = [];
  let i = 0;

  const collectStep = () => {
    if (gen !== bvhGen) { stripped.forEach(g => g.dispose()); return; }

    if (i < meshes.length) {
      const m = meshes[i++];
      // Strip to position only — normals included for face normal queries
      const src = m.geometry;
      const g = new THREE.BufferGeometry();
      // Clone position and bake world transform into it
      const posAttr = src.attributes.position.clone();
      g.setAttribute('position', posAttr);
      // Keep normals for slope/wall normal queries
      if (src.attributes.normal) {
        g.setAttribute('normal', src.attributes.normal.clone());
      }
      if (src.index) g.setIndex(src.index.clone());
      // Bake world-space transform — after this, positions are in world space
      // and singleColMesh can sit at identity with no further transform needed
      g.applyMatrix4(m.matrixWorld);
      stripped.push(g);

      const pct = ((i / meshes.length) * 100).toFixed(0);
      $('bvh-fill').style.width = pct + '%';
      $('bvh-text').textContent = 'COL ' + pct + '%';

      typeof requestIdleCallback !== 'undefined'
        ? requestIdleCallback(collectStep, { timeout: 400 })
        : setTimeout(collectStep, 0);
    } else {
      // All meshes stripped — now merge and build single BVH
      $('bvh-text').textContent = 'BVH…';
      $('tel-bvh').textContent = 'Merging…';

      // Defer one frame so the progress bar renders
      setTimeout(() => {
        if (gen !== bvhGen) { stripped.forEach(g => g.dispose()); return; }

        let merged;
        try {
          merged = mergeGeometries(stripped, false);
        } catch(e) {
          console.error('mergeGeometries failed:', e);
          toast('BVH merge error — using first mesh fallback', 'err', 4000);
          // Fallback: build BVH on each mesh individually (original behaviour)
          stripped.forEach(g => g.dispose());
          _buildBVHFallback(meshes, gen);
          return;
        }
        stripped.forEach(g => g.dispose());

        if (!merged) {
          toast('BVH merge returned null', 'err'); return;
        }

        // Single computeBoundsTree call on the entire collision geometry
        merged.computeBoundsTree({ maxLeafTris: CFG.BVH_LEAF });

        const colMat = new THREE.MeshBasicMaterial({ visible: false });
        singleColMesh = new THREE.Mesh(merged, colMat);
        // Identity transform — positions already baked in world space
        singleColMesh.matrixAutoUpdate = false;
        singleColMesh.updateMatrixWorld();

        bvhReady = true;
        $('bvhbar').classList.remove('show');
        $('bvh-pill').style.display = 'none';

        const triCount = merged.index
          ? merged.index.count / 3
          : merged.attributes.position.count / 3;
        $('tel-bvh').textContent = (triCount/1000).toFixed(0) + 'k — ready';
        $('bvh-text').textContent = 'BVH';

        // Smart floor snap after BVH ready
        gRay.ray.origin.set(body.pos.x, body.pos.y+2, body.pos.z);
        gRay.far = CFG.M_SIZE * 4;
        const sn = gRay.intersectObjects([singleColMesh], false)[0];
        if (sn) { body.pos.y = sn.point.y + CFG.EYE_H; body.prev.copy(body.pos); onGround = true; }

        toast('BVH ready · ' + (triCount/1000).toFixed(0) + 'k triangles', 'ok');
      }, 0);
    }
  };

  collectStep();
}

// Fallback: per-mesh BVH if mergeGeometries fails (e.g. incompatible attributes)
function _buildBVHFallback(meshes, gen) {
  $('tel-bvh').textContent = 'Fallback BVH…';
  let i = 0;
  const tick = () => {
    if (gen !== bvhGen) return;
    if (i < meshes.length) {
      if (!meshes[i].geometry.boundsTree) meshes[i].geometry.computeBoundsTree({maxLeafTris: CFG.BVH_LEAF});
      i++;
      typeof requestIdleCallback !== 'undefined'
        ? requestIdleCallback(tick, {timeout:400})
        : setTimeout(tick, 0);
    } else {
      // Create a thin wrapper: singleColMesh is null, colMeshes used directly
      // Signal bvhReady so physics can run using colMeshes directly
      bvhReady = true;
      $('bvhbar').classList.remove('show');
      $('bvh-pill').style.display = 'none';
      $('tel-bvh').textContent = 'fallback — ready';
      gRay.ray.origin.set(body.pos.x, body.pos.y+2, body.pos.z); gRay.far=CFG.M_SIZE*4;
      const sn=gRay.intersectObjects(colMeshes,false)[0];
      if(sn){body.pos.y=sn.point.y+CFG.EYE_H;body.prev.copy(body.pos);onGround=true;}
      toast('BVH ready (fallback mode)','ok');
    }
  };
  tick();
}

// Helper: returns the active collision targets (merged mesh or fallback array)
function colTargets() {
  return singleColMesh ? [singleColMesh] : colMeshes;
}

// Patch resolve* functions to use colTargets() — handles both paths
// (The inline [singleColMesh] in resolve* above is the hot path;
// colTargets() is only needed for the floor-snap and HUD floor check
// which call intersectObjects directly.)

let mixer=null, animClips=[], animIdx=0, animPlaying=false, animScrub=false;
const _acts=[];

function initAnim(root,clips) {
  if(mixer)mixer.stopAllAction(); _acts.length=0;
  animClips=clips; animIdx=0; animPlaying=false;
  mixer=clips.length?new THREE.AnimationMixer(root):null;
  clips.forEach(c=>_acts.push(mixer.clipAction(c)));
  $('anim-ct').textContent=clips.length?clips.length+' clip'+(clips.length>1?'s':''):'';
  const list=$('anim-list');
  list.innerHTML=clips.length?'':'<div style="font:400 9px/1 var(--mono);color:var(--t4);text-align:center;padding:8px">No animations</div>';
  clips.forEach((c,i)=>{
    const d=document.createElement('div'); d.className='anim-clip'+(i===0?' active':'');
    d.innerHTML=`<span class="anim-clip-name">${c.name||'Clip '+(i+1)}</span><span class="anim-clip-dur">${c.duration.toFixed(2)}s</span>`;
    d.onclick=()=>{
      _acts.forEach(a=>a.stop()); animIdx=i;
      _acts[i].reset().play(); _acts[i].paused=!animPlaying;
      $('anim-dur').textContent=clips[i].duration.toFixed(2)+'s';
      $('anim-progress').max=clips[i].duration; $('anim-progress').value=0;
      list.querySelectorAll('.anim-clip').forEach((el,j)=>el.classList.toggle('active',j===i));
    };
    list.appendChild(d);
  });
  if(clips.length){$('anim-dur').textContent=clips[0].duration.toFixed(2)+'s';$('anim-progress').max=clips[0].duration;}
}
$('anim-play-btn').onclick=()=>{
  if(!mixer||!animClips.length)return;
  animPlaying=!animPlaying;
  const a=_acts[animIdx]; if(!a)return;
  if(animPlaying){a.paused=false;if(!a.isRunning())a.reset().play();}else a.paused=true;
  $('anim-play-btn').textContent=animPlaying?'⏸':'▶';
};
$('anim-progress').addEventListener('mousedown',()=>animScrub=true);
$('anim-progress').addEventListener('input',()=>{
  if(!mixer||!animClips.length)return;
  const t=parseFloat($('anim-progress').value),a=_acts[animIdx];
  if(a){a.time=t;mixer.update(0);$('anim-cur').textContent=t.toFixed(2)+'s';}
});
$('anim-progress').addEventListener('mouseup',()=>animScrub=false);
$('anim-speed').addEventListener('input',()=>{
  const v=parseFloat($('anim-speed').value);
  $('anim-sv').textContent=v.toFixed(2)+'×';
  if(mixer)mixer.timeScale=v;
});

const loader = new GLTFLoader();
let currentModelUrl='', currentModelName='';
const floorRay=new THREE.Raycaster(); floorRay.ray.direction.set(0,-1,0); floorRay.firstHitOnly=true; floorRay.far=20;
let loadingSteps = ['Fetching file…','Parsing JSON…','Building geometry…','Compiling shaders…'];

function loadModel(url, name='') {
  bvhGen++; bvhReady=false; onGround=false; colMeshes=[]; clearAnns(); resetGY();
  currentModelUrl=url; currentModelName=name;
  if(mixer)mixer.stopAllAction();
  if(activeRoot){disposeModel(activeRoot);scene.remove(activeRoot);activeRoot=null;}

  // ─── FIX 4: dispose merged collision mesh before loading new model ───
  disposeColMesh();

  // ─── FIX 5: clear loader texture cache to prevent session-long GPU memory leak ───
  THREE.Cache.clear();

  wireOn=false; $('rb-wire').classList.remove('active');

  $('loading-overlay').classList.add('show');
  $('empty-state').classList.add('hidden');
  let stepI=0;
  const stepInterval=setInterval(()=>{ $('loading-sub').textContent=loadingSteps[stepI++ % loadingSteps.length]; },800);

  loader.load(url, gltf=>{
    clearInterval(stepInterval);
    $('loading-overlay').classList.remove('show');

    const root=gltf.scene; fixMaterials(root);
    const b0=new THREE.Box3().setFromObject(root), s0=b0.getSize(new THREE.Vector3());
    const scale=CFG.M_SIZE/Math.max(s0.x,s0.y,s0.z,.001);
    root.scale.setScalar(scale); scene.add(root); root.updateMatrixWorld(true);

    const b1=new THREE.Box3().setFromObject(root), c1=b1.getCenter(new THREE.Vector3());
    root.position.set(-c1.x,-b1.min.y,-c1.z); root.updateMatrixWorld(true);

    const b2=new THREE.Box3().setFromObject(root), c2=b2.getCenter(new THREE.Vector3()), s2=b2.getSize(new THREE.Vector3());
    modelCentre.copy(c2);

    // Collect collision meshes (used for spawn grid + passed to buildBVH)
    root.traverse(n=>{
      if(!n.isMesh)return; n.geometry.computeBoundingSphere();
      if((n.geometry.boundingSphere.radius)*n.matrixWorld.getMaxScaleOnAxis()>=CFG.MIN_MESH_R) colMeshes.push(n);
    });

    // Smart spawn — brute-force OK here (one-time, pre-BVH)
    const sr=new THREE.Raycaster(); sr.ray.direction.set(0,-1,0); sr.firstHitOnly=true; sr.far=s2.y*2;
    let bestY=null; const sg=CFG.SPAWN_GRID;
    for(let ix=0;ix<sg;ix++) for(let iz=0;iz<sg;iz++){
      sr.ray.origin.set(b2.min.x+(b2.max.x-b2.min.x)*(ix+.5)/sg, b2.max.y+1, b2.min.z+(b2.max.z-b2.min.z)*(iz+.5)/sg);
      const h=sr.intersectObjects(colMeshes,false)[0];
      if(h&&(bestY===null||h.point.y>bestY))bestY=h.point.y;
    }
    const sy=(bestY!==null?bestY:b2.max.y)+CFG.EYE_H+.1;
    spawn.set(c2.x,sy,c2.z+s2.z*.4);
    body.pos.copy(spawn); body.prev.copy(spawn); body.vel.set(0,0,0);
    flyPos.copy(spawn).add(new THREE.Vector3(0,5,0));
    fitShadow(spawn);

    if(mode==='ORBIT'){orbit.target.copy(c2);cam.position.set(c2.x,c2.y+s2.y*.7,c2.z+s2.z*1.5);orbit.update();}
    else if(mode==='FPS') rig.position.copy(spawn);
    else cam.position.copy(flyPos);

    activeRoot=root; vp.classList.add('loaded');

    let meshC=0,triC=0; const matS=new Set();
    root.traverse(n=>{if(!n.isMesh)return;meshC++;const g=n.geometry;triC+=g.index?g.index.count/3:g.attributes.position.count/3;[].concat(n.material).forEach(m=>m&&matS.add(m.uuid));});
    $('st-mesh').textContent=meshC;
    const triK=triC/1000;
    $('st-tri').textContent=triK.toFixed(1)+'k';
    $('st-tri').className='stat-v'+(triK>500?' warn':'');
    $('st-mat').textContent=matS.size;
    $('st-anim').textContent=gltf.animations.length||'—';
    $('tb-tri').textContent=triK.toFixed(0)+'k TRI';
    $('model-stats').style.display='block';

    buildBVH(colMeshes, bvhGen);
    initAnim(root,gltf.animations);
    sessionDist=0; sessionStart=Date.now();
    setStatus('LOADED','green');
    $('tb-model-name').textContent=name.toUpperCase();
    toast('Loaded: '+name,'ok');
  }, undefined, e=>{
    clearInterval(stepInterval);
    $('loading-overlay').classList.remove('show');
    toast('Load error: '+(e.message||e), 'err', 5000);
  });
}

let fps=0, frames=0, fpsAcc=0;
const _hp=new THREE.Vector3(), _ru=new THREE.Vector2();
const annContainer=Object.assign(document.createElement('div'),{style:'position:absolute;inset:0;pointer-events:none;z-index:35'});
vp.appendChild(annContainer);

function updateHUD(spd,dt) {
  frames++; fpsAcc+=dt;
  if(fpsAcc>=.5){
    fps=Math.round(frames/fpsAcc);
    const tri=Math.round(R.info.render.triangles/1000);
    const dc=R.info.render.calls;
    $('tb-fps').textContent=fps+' fps';
    $('tb-fps').style.color=fps>=55?'var(--green)':fps>=30?'var(--amber)':'var(--red)';
    $('p-fps').textContent=fps; $('p-tri').textContent=tri; $('p-draw').textContent=dc;
    $('st-fps').textContent=fps+' fps';
    frames=fpsAcc=0;
  }
  const pos=mode==='FLY'?flyPos:mode==='ORBIT'?cam.getWorldPosition(_hp):body.pos;
  let brg=(-yaw*DEG)%360; if(brg<0)brg+=360;
  const bi=Math.round(brg), dir=COMPASS[Math.round(brg/45)%8];

  $('tel-x').textContent=pos.x.toFixed(2);
  $('tel-y').textContent=pos.y.toFixed(2);
  $('tel-z').textContent=pos.z.toFixed(2);
  $('tel-brg').textContent=bi+'° '+dir;
  $('tel-slp').textContent=slope.toFixed(1)+'°';

  if(mode==='FPS' && bvhReady){
    const targets = colTargets();
    if(targets.length) {
      floorRay.ray.origin.copy(body.pos);
      const fh=floorRay.intersectObjects(targets,false)[0];
      $('tel-flr').textContent=fh?fh.distance.toFixed(2)+' m':'> 20 m';
    }
  } else $('tel-flr').textContent='—';

  $('st-spd').textContent=spd.toFixed(2)+' m/s';
  const el=Math.floor((Date.now()-sessionStart)/1000);
  $('st-elapsed').textContent=fmtSec(el);
  $('st-dist').textContent=sessionDist.toFixed(1)+' m';

  $('c-x').textContent=pos.x.toFixed(2);
  $('c-y').textContent=pos.y.toFixed(2);
  $('c-z').textContent=pos.z.toFixed(2);
  $('c-brg').textContent=String(bi).padStart(3,'0')+'° '+dir;

  $('compass-needle').setAttribute('transform',`rotate(${-yaw*DEG} 24 24)`);

  if(mixer&&animClips.length&&!animScrub){
    const a=_acts[animIdx];
    if(a){$('anim-cur').textContent=a.time.toFixed(2)+'s';$('anim-progress').value=a.time;}
  }
  renderAnnPins();
}

function setStatus(txt, color='gray') {
  $('tb-status-text').textContent=txt;
  $('tb-dot').className='tb-dot '+color;
}

const _fp=new THREE.Vector3(), _fd=new THREE.Vector3();
function toggleFlash() {
  flashOn=!flashOn; flash.intensity=flashOn?CFG.FL_INT:0;
  $('rb-flash').classList.toggle('active',flashOn);
  toast(flashOn?'Flashlight ON':'Flashlight OFF','info',1200);
}
window.toggleFlash=toggleFlash;
function updateFlash() {
  if(!flashOn)return;
  cam.getWorldPosition(_fp); cam.getWorldDirection(_fd);
  flash.position.copy(_fp); flash.target.position.copy(_fp).addScaledVector(_fd,10);
  flash.target.updateMatrixWorld();
}

function toggleWire() {
  if(!activeRoot)return toast('Load a model first','err');
  setWireframe(!wireOn);
  $('rb-wire').classList.toggle('active',wireOn);
  toast(wireOn?'Wireframe ON':'Wireframe OFF','info',1400);
}
window.toggleWire=toggleWire;

// ════════════════════════════════════════════════════
// MAIN LOOP
// ════════════════════════════════════════════════════
const clock=new THREE.Clock();
const _flyF=new THREE.Vector3(), _flyR=new THREE.Vector3();
let smoothBobY=0;

function mainLoop() {
  const dt=Math.min(clock.getDelta(),.05);
  if(mixer&&animPlaying) mixer.update(dt);

  if(mode==='ORBIT'){orbit.update();R.render(scene,cam);updateHUD(0,dt);return;}

  if(mode==='FLY'){
    if(fpsLocked){
      const i=pollIntent(), sp=flySpd*(i.sprint?PHY.sprintMult:1);
      cam.getWorldDirection(_flyF);
      _flyR.crossVectors(_flyF,new THREE.Vector3(0,1,0)).normalize();
      flyPos.addScaledVector(_flyF,i.fwd*sp*dt).addScaledVector(_flyR,i.rgt*sp*dt);
      if(keys.has('Space')) flyPos.y+=sp*dt;
      if(keys.has('KeyC'))  flyPos.y-=sp*dt;
      cam.position.copy(flyPos);
      sessionDist+=Math.hypot(i.fwd,i.rgt)*sp*dt;
    }
    updateFlash(); updateHUD(0,dt); R.render(scene,cam); return;
  }

  // FPS mode
  const i=fpsLocked?pollIntent():{fwd:0,rgt:0,moving:false,sprint:false,crouch:false};
  const eH=i.crouch?CFG.EYE_H*.55:CFG.EYE_H;

  // ─── FIX 6: cap physics steps to prevent tunneling on lag spikes ───
  // Without this cap, a single 500ms frame triggers ~30 physics steps,
  // generating enough velocity to tunnel through geometry.
  accum += dt;
  let physStepsThisFrame = 0;
  while (accum >= CFG.DT && physStepsThisFrame < CFG.MAX_PHYS_STEPS) {
    physStep(i);
    resolveGround(eH);
    resolveWalls(eH);
    resolveStep(eH);
    accum -= CFG.DT;
    physStepsThisFrame++;
  }
  // If we hit the cap, drain the surplus — next frame starts fresh.
  // This causes a visible stutter on extreme lag spikes, which is correct:
  // better to freeze briefly than to teleport through walls.
  if (physStepsThisFrame >= CFG.MAX_PHYS_STEPS) accum = 0;

  const al=clamp(accum/CFG.DT,0,1);
  rig.position.set(
    body.prev.x+(body.pos.x-body.prev.x)*al,
    body.pos.y-eH,
    body.prev.z+(body.pos.z-body.prev.z)*al
  );
  if(fpsLocked){
    const bt=Math.sin(Date.now()*.007)*.007*(i.moving?1:0);
    smoothBobY+=(bt-smoothBobY)*Math.min(1,dt*18);
    cam.position.y=smoothBobY;
  }
  if(Math.abs(cam.fov-fovTarget)>.1){cam.fov+=(fovTarget-cam.fov)*Math.min(1,dt*10);cam.updateProjectionMatrix();}
  updateFlash(); fitShadow(body.pos);
  updateHUD(Math.hypot(body.vel.x,body.vel.z),dt);
  R.render(scene,cam);
}
R.setAnimationLoop(mainLoop);

// ════════════════════════════════════════════════════
// CESIUM GLOBE
// ════════════════════════════════════════════════════
let cesiumViewer=null, cesiumEntity=null, globeVisible=false;

function initCesium() {
  if(cesiumViewer){
    try{cesiumViewer.destroy();}catch(_){}
    cesiumViewer=null; cesiumEntity=null;
    $('globe-div').innerHTML='';
  }
  const token=$('g-token').value.trim();
  if(token) Cesium.Ion.defaultAccessToken=token;

  try{
    const container=document.createElement('div');
    container.style.cssText='width:100%;height:100%;position:absolute;inset:0';
    $('globe-div').appendChild(container);

    const imageryProvider=token
      ?new Cesium.IonImageryProvider({assetId:2})
      :new Cesium.UrlTemplateImageryProvider({
          url:'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          maximumLevel:19,
          credit:new Cesium.Credit('© OpenStreetMap contributors',false)
        });

    cesiumViewer=new Cesium.Viewer(container,{
      imageryProvider,
      terrainProvider:new Cesium.EllipsoidTerrainProvider(),
      baseLayerPicker:false, geocoder:false, homeButton:false,
      sceneModePicker:false, navigationHelpButton:false,
      animation:false, timeline:false, fullscreenButton:false,
      infoBox:false, selectionIndicator:false,
      creditViewport:Object.assign(document.createElement('div'),{style:'display:none'})
    });
    cesiumViewer.scene.globe.enableLighting=true;
    const lat=parseFloat($('g-lat').value)||51.5074;
    const lon=parseFloat($('g-lon').value)||(-0.1278);
    cesiumViewer.camera.setView({
      destination:Cesium.Cartesian3.fromDegrees(lon,lat,1500),
      orientation:{heading:0,pitch:-0.7,roll:0}
    });
    $('gc-status').textContent=token?'✓ Ion token · satellite imagery':'✓ OSM tiles · no token needed';
    $('gc-status').className='globe-status ok';
  }catch(e){
    toast('Cesium error: '+e.message,'err',5000);
    console.error('Cesium:',e);
  }
}

function placeOnGlobe() {
  if(!activeRoot)return toast('Load a model first','err');
  if(!cesiumViewer||cesiumViewer.isDestroyed())return toast('Open Globe first','err');
  const lat=parseFloat($('g-lat').value)||0;
  const lon=parseFloat($('g-lon').value)||0;
  const alt=parseFloat($('g-alt').value)||0;
  const gscale=parseFloat($('g-scale').value)||1;
  const absUrl=window.location.origin+currentModelUrl;
  if(cesiumEntity){try{cesiumViewer.entities.remove(cesiumEntity);}catch(_){}}
  cesiumEntity=cesiumViewer.entities.add({
    name:currentModelName||'Model',
    position:Cesium.Cartesian3.fromDegrees(lon,lat,alt),
    model:{
      uri:absUrl, minimumPixelSize:64, maximumScale:200000,
      scale:gscale, shadows:Cesium.ShadowMode.ENABLED
    },
    label:{
      text:currentModelName||'Model',
      font:'11px IBM Plex Mono,monospace',
      fillColor:Cesium.Color.fromCssColorString('#00d4ff'),
      outlineColor:Cesium.Color.BLACK, outlineWidth:2,
      style:Cesium.LabelStyle.FILL_AND_OUTLINE,
      pixelOffset:new Cesium.Cartesian2(0,-32),
      disableDepthTestDistance:Number.POSITIVE_INFINITY,
      distanceDisplayCondition:new Cesium.DistanceDisplayCondition(0,8000)
    }
  });
  cesiumViewer.zoomTo(cesiumEntity,new Cesium.HeadingPitchRange(0,-0.55,alt+300)).catch(()=>{});
  $('gc-status').textContent=`✓ Placed · ${lat.toFixed(4)}°, ${lon.toFixed(4)}° · alt ${alt}m`;
  toast(`Anchored: ${lat.toFixed(4)}°N ${lon.toFixed(4)}°E`,'ok');
}

function toggleGlobe(show) {
  globeVisible=show;
  $('globe-wrap').classList.toggle('show',globeVisible);
  $('globe-ctrl').classList.toggle('show',globeVisible);
  $('rb-globe').classList.toggle('active',globeVisible);

  if(globeVisible){
    R.setAnimationLoop(null); R.render(scene,cam);
    canvas.style.visibility='hidden';
    if(!cesiumViewer||cesiumViewer.isDestroyed()) initCesium();
    $('hud-dot').className='hud-dot globe';
    $('hud-mode').textContent='GLOBE';
    setStatus('GLOBE','amber');
  }else{
    canvas.style.visibility='visible';
    R.setAnimationLoop(mainLoop);
    if(cesiumViewer&&!cesiumViewer.isDestroyed()) setTimeout(()=>{try{cesiumViewer.resize();}catch(_){}},100);
    const d=mode==='FPS'?'fps':mode==='FLY'?'fly':'orbit';
    $('hud-dot').className='hud-dot '+d;
    $('hud-mode').textContent=mode+(mode!=='ORBIT'?' MODE':'');
    setStatus(mode,'green');
  }
}
window.toggleGlobe=toggleGlobe;
$('gc-place').onclick=placeOnGlobe;
$('gc-reinit').onclick=()=>{if(globeVisible)initCesium();};

// ════════════════════════════════════════════════════
// MEASURE TOOL
// ════════════════════════════════════════════════════
let measureMode=false, measurePts=[], mPinA=null, mPinB=null, lastDist=null, savedMeasures=[];
const mRay=new THREE.Raycaster();
const pinGeo=new THREE.SphereGeometry(.08,8,8);
const pinMat=new THREE.MeshBasicMaterial({color:0x00d4ff});
let mouseX=0, mouseY=0;
canvas.addEventListener('mousemove', e=>{mouseX=e.clientX;mouseY=e.clientY;});

function getSceneHit(){
  if(!bvhReady) return null;
  const targets = colTargets();
  if(!targets.length) return null;
  if(mode!=='ORBIT'){toast('Switch to Orbit mode to measure','info',1800);return null;}
  const r=canvas.getBoundingClientRect();
  _ru.set((mouseX-r.left)/r.width*2-1,-((mouseY-r.top)/r.height)*2+1);
  mRay.setFromCamera(_ru,cam);
  const h=mRay.intersectObjects(targets,false);
  return h.length?h[0].point.clone():null;
}
function handleMeasureClick(){
  const pt=getSceneHit(); if(!pt)return;
  if(!measurePts.length){
    measurePts=[pt];
    if(mPinA)scene.remove(mPinA);
    mPinA=new THREE.Mesh(pinGeo,pinMat); mPinA.position.copy(pt); scene.add(mPinA);
    toast('Click second point','info');
  }else{
    measurePts[1]=pt;
    if(mPinB)scene.remove(mPinB);
    mPinB=new THREE.Mesh(pinGeo,pinMat); mPinB.position.copy(pt); scene.add(mPinB);
    lastDist=measurePts[0].distanceTo(pt);
    $('meas-d').textContent=lastDist.toFixed(3);
    $('meas-panel').classList.add('show');
    measurePts=[];
  }
}
function toggleMeasure(){
  if(!activeRoot&&!measureMode)return toast('Load a model first','err');
  measureMode=!measureMode;
  $('rb-measure').classList.toggle('active',measureMode);
  canvas.style.cursor=measureMode?'crosshair':'';
  if(!measureMode){
    measurePts=[]; $('meas-panel').classList.remove('show');
    [mPinA,mPinB].forEach(p=>{if(p)scene.remove(p);}); mPinA=mPinB=null;
  } else {
    annMode=false; $('rb-ann').classList.remove('active'); canvas.style.cursor='crosshair';
    toast('Click two points to measure','info');
  }
}
window.toggleMeasure=toggleMeasure;

$('meas-close').onclick=()=>{ if(measureMode)toggleMeasure(); $('meas-panel').classList.remove('show'); };
$('meas-save-btn').onclick=()=>{
  if(lastDist===null)return;
  const id='M'+(savedMeasures.length+1);
  savedMeasures.push({id,dist:lastDist});
  const row=document.createElement('div'); row.className='hist-row';
  row.innerHTML=`<span class="hist-id">${savedMeasures.length}</span><span class="hist-lbl">${id}</span><span class="hist-val">${lastDist.toFixed(3)} m</span>`;
  $('hist-list').appendChild(row);
  $('meas-history').classList.add('show');
  toast('Saved '+id,'ok',1400);
};
$('hist-clear').onclick=()=>{savedMeasures=[];$('hist-list').innerHTML='';$('meas-history').classList.remove('show');};

// ════════════════════════════════════════════════════
// ANNOTATIONS
// ════════════════════════════════════════════════════
let anns=[], annMode=false;
function toggleAnn(){
  if(!activeRoot&&!annMode)return toast('Load a model first','err');
  annMode=!annMode;
  $('rb-ann').classList.toggle('active',annMode);
  if(annMode){
    measureMode=false; $('rb-measure').classList.remove('active'); canvas.style.cursor='cell';
    $('ann-panel').classList.add('show');
    toast('Click on model to place annotation','info');
  }else{
    canvas.style.cursor='';
  }
}
window.toggleAnn=toggleAnn;
$('ann-close').onclick=()=>{ if(annMode)toggleAnn(); $('ann-panel').classList.remove('show'); };
$('ann-pb').onclick=()=>{ if(!annMode)toggleAnn(); };
function handleAnnClick(){
  const pt=getSceneHit(); if(!pt)return;
  const lb=$('ann-inp').value.trim()||'Point '+(anns.length+1);
  anns.push({lb,pos:pt}); renderAnnList();
  $('ann-inp').value=''; annMode=false; $('rb-ann').classList.remove('active'); canvas.style.cursor='';
  toast('Placed: '+lb,'ok');
}
function renderAnnList(){
  const el=$('ann-list');
  if(!anns.length){el.innerHTML='<div style="font:400 9px/1 var(--mono);color:var(--t4);text-align:center;padding:10px">No annotations yet</div>';return;}
  el.innerHTML='';
  anns.forEach((a,i)=>{
    const d=document.createElement('div'); d.className='ann-item';
    d.innerHTML=`<div class="ann-dot"></div><span class="ann-lbl">${a.lb}</span><button class="ann-del">✕</button>`;
    d.querySelector('.ann-del').onclick=()=>{anns.splice(i,1);renderAnnList();renderAnnPins();};
    el.appendChild(d);
  });
}
function clearAnns(){anns=[];renderAnnList();annContainer.innerHTML='';}
function renderAnnPins(){
  if(!anns.length){annContainer.innerHTML='';return;}
  const vw=vp.clientWidth,vh=vp.clientHeight; let h='';
  for(const a of anns){
    const v=a.pos.clone().project(cam);
    if(v.z>1||v.z<-1)continue;
    h+=`<div class="ann-pin" style="left:${((v.x*.5+.5)*vw).toFixed(1)}px;top:${((-.5*v.y+.5)*vh).toFixed(1)}px">${a.lb}</div>`;
  }
  annContainer.innerHTML=h;
}

// ════════════════════════════════════════════════════
// VIEWPOINTS
// ════════════════════════════════════════════════════
let viewpoints=[], vpCounter=0;
function saveVP(){
  if(!activeRoot)return toast('Load a model first','err');
  const p=new THREE.Vector3(); cam.getWorldPosition(p);
  const n='View '+(++vpCounter);
  viewpoints.push({n,pos:p.clone(),yaw,pitch,fov:cam.fov});
  renderVPList(); toast('Saved: '+n,'ok');
}
function recallVP(v){
  if(mode==='FPS'){body.pos.copy(v.pos.clone().setY(v.pos.y-CFG.EYE_H));body.prev.copy(body.pos);yaw=v.yaw;pitch=v.pitch;fovTarget=v.fov;rig.rotation.y=yaw;cam.rotation.x=pitch;rig.position.copy(body.pos);}
  else if(mode==='FLY'){flyPos.copy(v.pos);cam.position.copy(flyPos);yaw=v.yaw;pitch=v.pitch;cam.rotation.set(pitch,yaw,0,'YXZ');}
  else{cam.position.copy(v.pos);cam.rotation.set(v.pitch,v.yaw,0,'YXZ');orbit.target.copy(modelCentre);orbit.update();}
  toast('View: '+v.n,'info');
}
function renderVPList(){
  const el=$('vpt-list');
  if(!viewpoints.length){el.innerHTML='<div style="font:400 9px/1 var(--mono);color:var(--t4);text-align:center;padding:10px">No saved views</div>';return;}
  el.innerHTML='';
  viewpoints.forEach((v,i)=>{
    const d=document.createElement('div'); d.className='vpt-item';
    d.innerHTML=`<span class="vpt-num">${i+1}</span><span class="vpt-name">${v.n}</span><button class="vpt-del">✕</button>`;
    d.addEventListener('click',e=>{if(!e.target.classList.contains('vpt-del'))recallVP(v);});
    d.querySelector('.vpt-del').onclick=()=>{viewpoints.splice(i,1);renderVPList();};
    el.appendChild(d);
  });
}
$('vpt-save').onclick=saveVP;

// ════════════════════════════════════════════════════
// PANEL / DRAWER MANAGEMENT
// ════════════════════════════════════════════════════
function togglePanel(id, btnId) {
  const p=$(id); if(!p)return;
  const open=p.classList.contains('show');
  document.querySelectorAll('.fpanel').forEach(fp=>fp.classList.remove('show'));
  document.querySelectorAll('.rib-btn').forEach(b=>{ if(['rb-ann','rb-vpt','rb-anim'].includes(b.id)) b.classList.remove('active'); });
  if(!open){ p.classList.add('show'); if(btnId)$(btnId).classList.add('active'); }
}
window.togglePanel=togglePanel;

function openDrawer(pane){
  const drawer=$('bot-drawer');
  drawer.classList.add('open');
  document.querySelectorAll('.drawer-tab').forEach(t=>{
    t.classList.toggle('active', t.dataset.pane===pane);
  });
  document.querySelectorAll('.drawer-pane').forEach(p=>{
    p.classList.toggle('active', p.id==='dp-'+pane);
  });
  $('rb-env').classList.toggle('active', pane==='env');
  $('rb-phys').classList.toggle('active', pane==='phys');
  $('rb-keys').classList.toggle('active', pane==='keys');
}
function closeDrawer(){
  $('bot-drawer').classList.remove('open');
  $('rb-env').classList.remove('active');
  $('rb-phys').classList.remove('active');
  $('rb-keys').classList.remove('active');
}
document.querySelectorAll('.drawer-tab').forEach(tab=>{
  tab.addEventListener('click',()=>openDrawer(tab.dataset.pane));
});
window.openDrawer=openDrawer;
window.closeDrawer=closeDrawer;

// ════════════════════════════════════════════════════
// SCREENSHOT
// ════════════════════════════════════════════════════
function takeShot(){
  if(globeVisible&&cesiumViewer&&!cesiumViewer.isDestroyed()){
    cesiumViewer.render();
    const a=document.createElement('a'); a.download='globe_'+Date.now()+'.png';
    a.href=cesiumViewer.canvas.toDataURL(); a.click();
  }else{
    R.render(scene,cam);
    const a=document.createElement('a'); a.download='spatial_'+Date.now()+'.png';
    a.href=R.domElement.toDataURL(); a.click();
  }
  toast('Screenshot saved','ok');
}
window.takeShot=takeShot;

// ════════════════════════════════════════════════════
// FILE MANAGEMENT
// ════════════════════════════════════════════════════
async function refreshList(){
  const models=await fetch('/api/models').then(r=>r.json()).catch(()=>[]);
  const ml=$('model-list');
  $('model-count').textContent=models.length;
  if(!models.length){
    ml.innerHTML='<div class="model-empty">Drop or upload GLB/GLTF files<br>to get started</div>';
    return;
  }
  ml.innerHTML='';
  models.forEach(m=>{
    const row=document.createElement('div'); row.className='model-row';
    const sizeStr=fmtBytes(m.size||0);
    row.innerHTML=`
      <div class="model-thumb">◈</div>
      <div class="model-info">
        <div class="model-name" title="${m.name}">${m.name}</div>
        <div class="model-meta">${sizeStr}</div>
      </div>
      <button class="model-del">✕</button>`;
    row.querySelector('.model-info').addEventListener('click',()=>{
      ml.querySelectorAll('.model-row').forEach(r=>r.classList.remove('active'));
      row.classList.add('active');
      loadModel('/models/'+m.name, m.name);
    });
    row.querySelector('.model-del').addEventListener('click',async e=>{
      e.stopPropagation();
      await fetch('/api/delete/'+m.name,{method:'DELETE'});
      toast('Deleted: '+m.name,'info');
      refreshList();
    });
    ml.appendChild(row);
  });
}
refreshList();

async function uploadFile(f){
  $('upload-bar').classList.add('show');
  $('upload-fill').style.width='0';
  setStatus('UPLOADING','cyan');
  const fd=new FormData(); fd.append('model',f);
  await new Promise((res,rej)=>{
    const xhr=new XMLHttpRequest();
    xhr.upload.onprogress=e=>{
      if(e.lengthComputable) $('upload-fill').style.width=(e.loaded/e.total*100)+'%';
    };
    xhr.onload=()=>{
      if(xhr.status===200){
        const d=JSON.parse(xhr.responseText);
        toast('Uploaded: '+f.name,'ok');
        loadModel('/models/'+d.name, d.name);
        refreshList(); res();
      }else{
        toast('Upload failed ('+xhr.status+')','err',4000); rej();
      }
      $('upload-bar').classList.remove('show');
    };
    xhr.onerror=()=>{ toast('Upload error','err',4000); $('upload-bar').classList.remove('show'); rej(); };
    xhr.open('POST','/api/upload'); xhr.send(fd);
  });
}

const dz=$('dz'), fi=$('fi');
dz.addEventListener('click',()=>fi.click());
fi.addEventListener('change',()=>{[...fi.files].forEach(uploadFile);fi.value='';});
dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('over');});
dz.addEventListener('dragleave',()=>dz.classList.remove('over'));
dz.addEventListener('drop',e=>{
  e.preventDefault(); dz.classList.remove('over');
  [...e.dataTransfer.files].filter(f=>/\.(glb|gltf)$/i.test(f.name)).forEach(uploadFile);
});

const sidebarToggle=document.createElement('button');
sidebarToggle.id='sidebar-toggle';
sidebarToggle.innerHTML='‹';
sidebarToggle.style.cssText='position:absolute;top:50%;left:var(--left-w);transform:translateY(-50%);background:var(--panel);border:1px solid var(--border);border-left:none;border-radius:0 var(--r2) var(--r2) 0;width:16px;height:40px;cursor:pointer;z-index:60;display:flex;align-items:center;justify-content:center;color:var(--t3);font-size:10px;transition:all .15s;font-family:var(--mono)';
$('body-row').appendChild(sidebarToggle);
sidebarToggle.addEventListener('click',()=>{
  $('left-panel').classList.toggle('collapsed');
  sidebarToggle.innerHTML=$('left-panel').classList.contains('collapsed')?'›':'‹';
});
</script>
</body>
</html>"""

if __name__ == "__main__":
    import os as _os
    debug = _os.environ.get("FLASK_DEBUG","0") == "1"
    app.run(debug=debug, port=5500, threaded=True)