"""
Human Detection Web App — YOLOv8 primary + Moondream2 fallback
pip install flask yt-dlp opencv-python-headless ultralytics pillow numpy moondream
python app.py → http://localhost:5000
"""
import os,json,base64,threading,uuid,time,tempfile,traceback,logging
from abc import ABC,abstractmethod
from dataclasses import dataclass,field
from io import BytesIO
from flask import Flask,request,Response,jsonify,render_template_string
from PIL import Image,ImageDraw,ImageEnhance
import numpy as np

logging.basicConfig(level=logging.INFO,format="[%(levelname)s] %(message)s")
log=logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════ CONFIG ════
@dataclass
class Config:
    yolo_model:     str   = "yolov8m.pt"       # swap: yolov8n/s/l/x
    yolo_conf:      float = 0.25
    yolo_classes:   list  = field(default_factory=lambda:[0])  # 0=person COCO
    md_model:       str   = "moondream-2b"
    md_conf_det:    float = 0.5
    md_conf_approx: float = 0.3
    max_dim:        int   = 640
    default_skip:   int   = 30
    min_box_frac:   float = 0.01
    md_min_box:     float = 0.02
    nms_thresh:     float = 0.4
    ydl_format:     str   = "best[ext=mp4][height<=720]/best[ext=mp4]/best"
    host:           str   = "0.0.0.0"
    port:           int   = 5000
    sse_poll_s:     float = 0.05
    jpeg_quality:   int   = 80
    brightness_ok:  float = 60.0
    md_prompts: list = field(default_factory=lambda:[
        "person from above","people overhead view",
        "shopper","human figure","person","pedestrian",
    ])
    md_yn_hits: list = field(default_factory=lambda:[
        "yes","person","people","human","man","woman",
        "someone","individual","figure","body","shopper",
    ])

CFG=Config()

# ══════════════════════════════════════════════════════════ UTILS ════
def pil_to_b64(img):
    buf=BytesIO(); img.save(buf,format="JPEG",quality=CFG.jpeg_quality)
    return base64.b64encode(buf.getvalue()).decode()

def fit(img):
    W,H=img.size; sc=min(1.0,CFG.max_dim/max(W,H))
    return img if sc==1.0 else img.resize((int(W*sc),int(H*sc)),Image.LANCZOS)

def enhance(img):
    img=img.convert("RGB")
    if np.array(img.convert("L"),dtype=np.float32).mean()>=CFG.brightness_ok: return img
    a=np.array(img,dtype=np.float32); lo,hi=a.min(),a.max()
    if hi-lo>10: a=(a-lo)/(hi-lo)*255
    img=Image.fromarray(a.astype(np.uint8))
    return ImageEnhance.Brightness(ImageEnhance.Contrast(img).enhance(1.5)).enhance(1.3)

def _iou(a,b):
    ix1=max(a["x1"],b["x1"]); iy1=max(a["y1"],b["y1"])
    ix2=min(a["x2"],b["x2"]); iy2=min(a["y2"],b["y2"])
    inter=max(0,ix2-ix1)*max(0,iy2-iy1)
    return 0.0 if not inter else inter/((a["x2"]-a["x1"])*(a["y2"]-a["y1"])+(b["x2"]-b["x1"])*(b["y2"]-b["y1"])-inter)

def nms(dets):
    kept=[]
    for d in dets:
        if not any(_iou(d,k)>CFG.nms_thresh for k in kept): kept.append(d)
    return kept

def mkbox(x1,y1,x2,y2,conf,**kw): return {"x1":x1,"y1":y1,"x2":x2,"y2":y2,"conf":round(conf,2),**kw}
def norm(x1,y1,x2,y2,W,H,conf):   return mkbox(x1/W,y1/H,x2/W,y2/H,conf)
def to_api(d): return {"x_min":d["x1"],"y_min":d["y1"],"x_max":d["x2"],"y_max":d["y2"],"conf":d["conf"],**{k:v for k,v in d.items() if k not in("x1","y1","x2","y2","conf")}}

def draw_boxes(img,dets):
    img=img.copy(); draw=ImageDraw.Draw(img,"RGBA"); W,H=img.size
    for d in dets:
        x1,y1,x2,y2=d["x1"]*W,d["y1"]*H,d["x2"]*W,d["y2"]*H
        conf=d.get("conf",1.0); alpha=int(80+170*conf); approx=d.get("approximate",False)
        oc,fc,lbl,lb=((255,220,60,alpha),(255,220,60,20),f"HUMAN~ {int(conf*100)}%",(255,220,60)) if approx else ((255,140,30,alpha),(255,140,30,18),f"HUMAN {int(conf*100)}%",(255,140,30))
        draw.rectangle([x1,y1,x2,y2],outline=oc,width=2); draw.rectangle([x1,y1,x2,y2],fill=fc)
        lw=len(lbl)*7+8; draw.rectangle([x1,max(0,y1-18),x1+lw,y1],fill=lb)
        draw.text((x1+4,max(0,y1-16)),lbl,fill=(0,0,0))
    return img.convert("RGB")

# ══════════════════════════════════════════════════════════ DETECTORS ════
class BaseDetector(ABC):
    name="base"; ready=False
    @abstractmethod
    def detect(self,img) -> list: ...

class YOLODetector(BaseDetector):
    name="yolo"
    def __init__(self):
        try:
            from ultralytics import YOLO
            self._m=YOLO(CFG.yolo_model); self.ready=True; log.info("YOLOv8 ready")
        except Exception as e: log.error(f"YOLOv8: {e}")
    def detect(self,img):
        W,H=img.size; dets=[]
        for r in self._m(img,classes=CFG.yolo_classes,conf=CFG.yolo_conf,verbose=False):
            for b in r.boxes:
                x1,y1,x2,y2=b.xyxy[0].tolist()
                if (x2-x1)/W<CFG.min_box_frac or (y2-y1)/H<CFG.min_box_frac: continue
                dets.append(norm(x1,y1,x2,y2,W,H,float(b.conf[0])))
        return dets

class MoondreamDetector(BaseDetector):
    name="moondream"
    def __init__(self):
        try:
            import moondream as md
            self._m=md.vl(model=CFG.md_model); self.ready=True; log.info("Moondream2 ready")
        except Exception as e: log.warning(f"Moondream2: {e}")
    def detect(self,img):
        img=enhance(img)
        try: enc=self._m.encode_image(img)
        except Exception as e: log.error(f"MD encode: {e}"); return []
        dets=[]
        for p in CFG.md_prompts:
            try:
                for o in self._m.detect(enc,p).objects:
                    w,h=o.x_max-o.x_min,o.y_max-o.y_min
                    if w<CFG.md_min_box or h<CFG.md_min_box: continue
                    dets.append(mkbox(float(o.x_min),float(o.y_min),float(o.x_max),float(o.y_max),CFG.md_conf_det))
            except Exception as e: log.warning(f"MD detect({p}): {e}")
        dets=nms(dets)
        if not dets:
            try:
                ans=self._m.query(enc,"Is there a person, human, shopper, or individual visible in this image, including from an overhead or top-down angle?").answer.lower()
                if any(w in ans for w in CFG.md_yn_hits):
                    dets.append(mkbox(0,0,1,1,CFG.md_conf_approx,approximate=True,answer=ans))
            except Exception as e: log.warning(f"MD yn: {e}")
        return dets

class DetectionPipeline:
    """Walk detectors in order; first non-empty result wins."""
    def __init__(self,detectors):
        self.detectors=[d for d in detectors if d.ready]
        if not self.detectors: log.error("No detection model available.")
    def detect(self,img):
        for det in self.detectors:
            try: result=det.detect(img)
            except Exception as e: log.error(f"{det.name} crashed: {e}"); result=[]
            if result: return result,det.name
        return [],(self.detectors[-1].name if self.detectors else "none")
    def any_ready(self): return bool(self.detectors)
    @property
    def status(self): return {d.name:d.ready for d in self.detectors}

PIPELINE=DetectionPipeline([YOLODetector(),MoondreamDetector()])

# ══════════════════════════════════════════════════════════ JOBS ════
class Stats:
    __slots__=("frames","with_humans","max_humans","total_detections")
    def __init__(self): self.frames=self.with_humans=self.max_humans=self.total_detections=0
    def update(self,n):
        self.frames+=1; self.total_detections+=n
        if n: self.with_humans+=1; self.max_humans=max(self.max_humans,n)
    def as_dict(self): return {s:getattr(self,s) for s in self.__slots__}

class JobStore:
    def __init__(self): self._jobs={}
    def create(self,jid): self._jobs[jid]={"events":[],"done":False,"lock":threading.Lock()}
    def get(self,jid): return self._jobs.get(jid)
    def emit(self,jid,data):
        j=self._jobs[jid]
        with j["lock"]: j["events"].append(json.dumps(data))
    def stream(self,jid):
        j=self._jobs[jid]; cursor=0
        while True:
            with j["lock"]: batch=j["events"][cursor:]; done=j["done"]
            for ev in batch: yield f"data: {ev}\n\n"; cursor+=1
            if done and cursor>=len(j.get("events",[])): break
            time.sleep(CFG.sse_poll_s)

STORE=JobStore()

# ══════════════════════════════════════════════════════════ WORKER ════
def _download(url,tmpdir):
    import yt_dlp
    with yt_dlp.YoutubeDL({"outtmpl":os.path.join(tmpdir,"video.%(ext)s"),"format":CFG.ydl_format,"quiet":True,"no_warnings":True}) as ydl:
        info=ydl.extract_info(url,download=True)
    vf=next((os.path.join(tmpdir,f) for f in os.listdir(tmpdir) if f.startswith("video.")),None)
    return vf,info.get("title","Video")

def _process(jid,url,skip):
    emit=lambda d:STORE.emit(jid,d)
    try:
        import cv2
        emit({"type":"status","message":"Downloading …"})
        tmpdir=tempfile.mkdtemp(); vf,title=_download(url,tmpdir)
        if not vf: emit({"type":"error","message":"Download failed."}); return
        cap=cv2.VideoCapture(vf)
        total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        fps=cap.get(cv2.CAP_PROP_FPS) or 30.0; ns=max(1,total//skip)
        emit({"type":"info","title":title,"total_frames":total,"fps":round(fps,1),"duration":round(total/fps,1),"n_samples":ns})
        stats=Stats(); fi=proc=0; tl=[]
        while True:
            ret,frame=cap.read()
            if not ret: break
            if fi%skip==0:
                img=fit(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)))
                dets,src=PIPELINE.detect(img); n=len(dets); ts=round(fi/fps,2)
                stats.update(n); tl.append({"t":ts,"n":n})
                emit({"type":"frame","index":proc,"total":ns,"timestamp":ts,"count":n,"source":src,
                      "detections":[to_api(d) for d in dets],"image":pil_to_b64(draw_boxes(img,dets)),"stats":stats.as_dict()})
                proc+=1
            fi+=1
        cap.release()
        try: os.remove(vf); os.rmdir(tmpdir)
        except: pass
        emit({"type":"done","stats":stats.as_dict(),"timeline":tl})
    except Exception as exc:
        log.error(traceback.format_exc())
        emit({"type":"error","message":str(exc),"trace":traceback.format_exc()})
    finally:
        j=STORE.get(jid)
        with j["lock"]: j["done"]=True

def start_job(jid,url,skip):
    STORE.create(jid); threading.Thread(target=_process,args=(jid,url,skip),daemon=True).start()

# ══════════════════════════════════════════════════════════ ROUTES ════
app=Flask(__name__)

@app.get("/")
def index(): return render_template_string(HTML)

@app.get("/health")
def health(): return jsonify({**PIPELINE.status,"any":PIPELINE.any_ready()})

@app.post("/process")
def process():
    body=request.get_json(silent=True) or {}
    url=body.get("url","").strip(); skip=max(1,int(body.get("frame_skip",CFG.default_skip)))
    if not url: return jsonify({"error":"No URL provided."}),400
    if not PIPELINE.any_ready(): return jsonify({"error":"No model loaded."}),500
    jid=str(uuid.uuid4()); start_job(jid,url,skip)
    return jsonify({"job_id":jid})

@app.get("/stream/<jid>")
def stream(jid):
    if not STORE.get(jid): return "Job not found",404
    return Response(STORE.stream(jid),mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ══════════════════════════════════════════════════════════ HTML ════
HTML=r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>HUMAN DETECT</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Rajdhani:wght@400;600;700&display=swap" rel="stylesheet"/>
<style>
:root{--bg:#0a0c0e;--surface:#111417;--border:#1e2428;--amber:#ff9f1c;--amber-dim:#7a4a00;--green:#39ff7a;--red:#ff3c3c;--blue:#38bdf8;--muted:#4a5568;--text:#cdd6e0;--mono:'Share Tech Mono',monospace;--sans:'Rajdhani',sans-serif}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;display:flex;flex-direction:column}
body::before{content:'';pointer-events:none;position:fixed;inset:0;z-index:9999;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.04) 2px,rgba(0,0,0,.04) 4px)}
header{padding:16px 32px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:16px}
.logo{font-family:var(--mono);font-size:20px;color:var(--amber);letter-spacing:4px;text-shadow:0 0 20px rgba(255,159,28,.45)}
.logo span{color:var(--muted)}.tagline{font-size:11px;letter-spacing:3px;color:var(--muted);text-transform:uppercase;margin-top:2px}
.header-right{margin-left:auto;display:flex;align-items:center;gap:14px}
.model-badge{font-family:var(--mono);font-size:9px;letter-spacing:1px;padding:3px 8px;border:1px solid;text-transform:uppercase}
.model-badge.on-yolo{color:var(--green);border-color:var(--green)}.model-badge.on-md{color:var(--blue);border-color:var(--blue)}.model-badge.off{color:var(--muted);border-color:var(--muted)}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s ease-in-out infinite}
.status-dot.inactive{background:var(--muted);box-shadow:none;animation:none}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.control-panel{padding:20px 32px;border-bottom:1px solid var(--border);display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap}
.field{display:flex;flex-direction:column;gap:6px}
label{font-family:var(--mono);font-size:9px;letter-spacing:2px;color:var(--muted);text-transform:uppercase}
input[type=text]{background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:13px;padding:10px 14px;width:460px;outline:none;transition:border-color .2s}
input[type=text]:focus{border-color:var(--amber)}input[type=text]::placeholder{color:var(--muted)}
.slider-row{display:flex;align-items:center;gap:10px}
input[type=range]{-webkit-appearance:none;width:120px;height:4px;background:var(--border);outline:none;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:14px;background:var(--amber);border-radius:0;cursor:pointer}
.slider-val{font-family:var(--mono);font-size:12px;color:var(--amber);min-width:24px}
button#run-btn{background:var(--amber);color:#000;border:none;font-family:var(--sans);font-weight:700;font-size:14px;letter-spacing:3px;text-transform:uppercase;padding:11px 28px;cursor:pointer;transition:background .15s,transform .1s}
button#run-btn:hover{background:#ffb84d;transform:translateY(-1px)}button#run-btn:active{transform:translateY(0)}button#run-btn:disabled{background:var(--amber-dim);cursor:not-allowed;transform:none}
.stats-bar{padding:14px 32px;border-bottom:1px solid var(--border);display:flex;gap:36px;flex-wrap:wrap;align-items:center}
.stat{display:flex;flex-direction:column;gap:2px}
.stat-label{font-family:var(--mono);font-size:9px;letter-spacing:2px;color:var(--muted);text-transform:uppercase}
.stat-value{font-family:var(--mono);font-size:22px;color:var(--amber);line-height:1}
.stat-value.green{color:var(--green)}.stat-value.red{color:var(--red)}
#engine-tag{font-family:var(--mono);font-size:9px;letter-spacing:1px;padding:3px 8px;border:1px solid var(--muted);color:var(--muted);text-transform:uppercase;margin-left:auto;align-self:center}
.progress-wrap{height:3px;background:var(--border)}
#progress-bar{height:100%;background:var(--amber);width:0%;transition:width .3s;box-shadow:0 0 10px var(--amber)}
#log-line{padding:6px 32px;font-family:var(--mono);font-size:11px;color:var(--muted);min-height:24px;border-bottom:1px solid var(--border)}
#log-line.error{color:var(--red)}
#timeline-wrap{padding:14px 32px 0;display:none}
#timeline-label{font-family:var(--mono);font-size:9px;letter-spacing:2px;color:var(--muted);margin-bottom:4px}
#timeline-canvas{width:100%;height:48px;display:block}
#done-banner{display:none;padding:12px 32px;background:rgba(57,255,122,.06);border-top:1px solid var(--green);border-bottom:1px solid var(--green);font-family:var(--mono);font-size:12px;color:var(--green);letter-spacing:1px}
#frame-grid{padding:20px 32px;display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;flex:1}
.frame-card{background:var(--surface);border:1px solid var(--border);overflow:hidden;position:relative;animation:fadeIn .25s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
.frame-card img{width:100%;display:block}
.frame-meta{padding:5px 10px;display:flex;justify-content:space-between;align-items:center;font-family:var(--mono);font-size:10px;color:var(--muted);border-top:1px solid var(--border)}
.badge{font-size:11px;font-weight:700;padding:1px 7px;letter-spacing:1px}
.badge-hit{color:var(--amber);border:1px solid var(--amber)}.badge-miss{color:var(--muted);border:1px solid var(--border)}
.src-tag{font-size:8px;letter-spacing:1px;padding:1px 4px;border:1px solid;text-transform:uppercase;margin-left:4px}
.src-yolo{color:var(--green);border-color:var(--green)}.src-md{color:var(--blue);border-color:var(--blue)}.src-none{color:var(--muted);border-color:var(--border)}
.frame-card.has-hit::after{content:attr(data-count) ' DETECTED';position:absolute;top:0;left:0;background:rgba(255,159,28,.12);border-bottom:1px solid var(--amber);border-right:1px solid var(--amber);font-family:var(--mono);font-size:9px;letter-spacing:1px;color:var(--amber);padding:3px 8px}
#empty-state{margin:60px auto;text-align:center;color:var(--muted)}
#empty-state pre{font-family:var(--mono);font-size:11px;line-height:1.4;color:#1e2a35;margin-bottom:20px;user-select:none}
#empty-state p{font-size:13px;letter-spacing:2px;text-transform:uppercase}
@media(max-width:600px){input[type=text]{width:100%}.control-panel,#frame-grid,.stats-bar{padding:12px 16px}}
</style>
</head>
<body>
<header>
  <div><div class="logo">HUMAN<span>//</span>DETECT</div><div class="tagline">Frame-by-frame · YOLOv8 + Moondream2</div></div>
  <div class="header-right">
    <span class="model-badge off" id="badge-yolo">YOLO —</span>
    <span class="model-badge off" id="badge-md">MOON —</span>
    <div class="status-dot inactive" id="status-dot"></div>
  </div>
</header>
<div class="control-panel">
  <div class="field" style="flex:1 1 auto">
    <label>Video URL (YouTube, MP4, …)</label>
    <input type=text id="url-input" placeholder="https://youtube.com/watch?v=…"/>
  </div>
  <div class="field">
    <label>Sample every N frames</label>
    <div class="slider-row">
      <input type=range id="skip-slider" min="5" max="120" value="30" oninput="$('skip-val').textContent=this.value"/>
      <span class="slider-val" id="skip-val">30</span>
    </div>
  </div>
  <button id="run-btn" onclick="run()">&#9654;  RUN</button>
</div>
<div class="stats-bar">
  <div class="stat"><div class="stat-label">Frames</div><div class="stat-value" id="s-frames">&#8212;</div></div>
  <div class="stat"><div class="stat-label">Detections</div><div class="stat-value green" id="s-detections">&#8212;</div></div>
  <div class="stat"><div class="stat-label">Hit Frames</div><div class="stat-value" id="s-hit-frames">&#8212;</div></div>
  <div class="stat"><div class="stat-label">Max/Frame</div><div class="stat-value red" id="s-max">&#8212;</div></div>
  <div class="stat"><div class="stat-label">Duration</div><div class="stat-value" id="s-duration">&#8212;</div></div>
  <div class="stat"><div class="stat-label">FPS</div><div class="stat-value" id="s-fps">&#8212;</div></div>
  <span id="engine-tag">ENGINE: &#8212;</span>
</div>
<div class="progress-wrap"><div id="progress-bar"></div></div>
<div id="log-line">Awaiting input &#8230;</div>
<div id="timeline-wrap"><div id="timeline-label">&#9658; HUMAN PRESENCE TIMELINE</div><canvas id="timeline-canvas" height="48"></canvas></div>
<div id="done-banner">&#10003;  ANALYSIS COMPLETE</div>
<div id="frame-grid">
  <div id="empty-state">
    <pre> &#9484;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9488;
 &#9474;  [  ]  [  ]  [  ]  [  ] &#9474;
 &#9474;  [ ? ]  [  ]  [ ? ]  [] &#9474;
 &#9492;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9472;&#9496;</pre>
    <p>Paste a video URL and press Run</p>
  </div>
</div>
<script>
const $=id=>document.getElementById(id);
let sse=null,tl=[],total=0;
fetch('/health').then(r=>r.json()).then(d=>{
  if(d.yolo){$('badge-yolo').textContent='YOLO \u2713';$('badge-yolo').className='model-badge on-yolo';}
  if(d.moondream){$('badge-md').textContent='MOON \u2713';$('badge-md').className='model-badge on-md';}
});
const lg=(msg,err=false)=>{$('log-line').textContent=msg;$('log-line').className=err?'error':'';};
const st=(id,v)=>{const e=$(id);if(e)e.textContent=v??'\u2014';};
const prog=p=>$('progress-bar').style.width=p+'%';
const fmt=s=>`${Math.floor(s/60)}:${(s%60).toFixed(1).padStart(4,'0')}`;
const srcTag=s=>s&&s!=='none'?(s.startsWith('yolo')?'<span class="src-tag src-yolo">YOLO</span>':'<span class="src-tag src-md">MD</span>'):'<span class="src-tag src-none">\u00b7</span>';
function addCard(ev){
  $('empty-state')?.remove();
  const card=document.createElement('div');
  card.className='frame-card'+(ev.count>0?' has-hit':'');
  if(ev.count>0)card.dataset.count=ev.count;
  const img=document.createElement('img');
  img.src='data:image/jpeg;base64,'+ev.image;img.loading='lazy';
  const meta=document.createElement('div');meta.className='frame-meta';
  meta.innerHTML=`<span>T:${fmt(ev.timestamp)}</span><span style="display:flex;align-items:center;gap:4px">${srcTag(ev.source)}<span class="badge ${ev.count>0?'badge-hit':'badge-miss'}">${ev.count>0?'\u2B21 '+ev.count:'\u00b7 \u00b7 \u00b7'}</span></span>`;
  card.append(img,meta);$('frame-grid').appendChild(card);
}
function drawTL(){
  const c=$('timeline-canvas');if(!tl.length)return;
  c.width=c.offsetWidth*devicePixelRatio;c.height=48*devicePixelRatio;
  const ctx=c.getContext('2d');ctx.scale(devicePixelRatio,devicePixelRatio);
  const W=c.offsetWidth,H=48,mx=Math.max(1,...tl.map(d=>d.n)),bw=Math.max(2,W/tl.length-1);
  ctx.clearRect(0,0,W,H);
  tl.forEach((d,i)=>{
    const x=(i/tl.length)*W,h=d.n>0?Math.max(4,(d.n/mx)*(H-6)):2;
    ctx.fillStyle=d.n>0?`rgba(255,159,28,${.3+.7*(d.n/mx)})`:'#1e2428';
    ctx.fillRect(x,H-h-1,bw,h);
  });
}
function run(){
  const url=$('url-input').value.trim();
  if(!url){lg('\u26a0 Enter a URL.',true);return;}
  const skip=parseInt($('skip-slider').value);
  if(sse)sse.close();
  $('frame-grid').innerHTML='';$('done-banner').style.display='none';$('timeline-wrap').style.display='none';
  tl=[];total=0;prog(0);
  ['s-frames','s-detections','s-hit-frames','s-max','s-duration','s-fps'].forEach(id=>st(id,'\u2014'));
  $('engine-tag').textContent='ENGINE: \u2014';
  const btn=$('run-btn');btn.disabled=true;$('status-dot').className='status-dot';lg('Submitting \u2026');
  fetch('/process',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,frame_skip:skip})})
    .then(r=>r.json()).then(d=>{
      if(d.error){lg('\u2715 '+d.error,true);btn.disabled=false;return;}
      sse=new EventSource('/stream/'+d.job_id);
      sse.onmessage=e=>{
        const ev=JSON.parse(e.data);
        if(ev.type==='status')lg(ev.message);
        else if(ev.type==='info'){
          total=ev.n_samples;st('s-duration',fmt(ev.duration));st('s-fps',ev.fps);
          lg(`\u25b8 ${ev.title} \u00b7 ${ev.total_frames} frames \u00b7 ~${ev.n_samples} samples`);
          $('timeline-wrap').style.display='block';
        }else if(ev.type==='frame'){
          prog(total?((ev.index+1)/total)*100:0);
          lg(`\u27f3 Frame ${ev.index+1}/${ev.total} @ ${fmt(ev.timestamp)} \u2014 ${ev.count} human(s) [${ev.source}]`);
          const s=ev.stats;
          st('s-frames',s.frames);st('s-detections',s.total_detections);st('s-hit-frames',s.with_humans);st('s-max',s.max_humans);
          if(ev.source)$('engine-tag').textContent='ENGINE: '+(ev.source.startsWith('yolo')?'YOLOv8':'Moondream2');
          addCard(ev);tl.push({t:ev.timestamp,n:ev.count});drawTL();
        }else if(ev.type==='done'){
          prog(100);lg(`\u2713 Done \u2014 ${ev.stats.frames} frames, ${ev.stats.total_detections} detections`);
          $('done-banner').style.display='block';btn.disabled=false;$('status-dot').className='status-dot inactive';sse.close();
        }else if(ev.type==='error'){
          lg('\u2715 '+ev.message,true);btn.disabled=false;$('status-dot').className='status-dot inactive';sse.close();console.error(ev.trace);
        }
      };
      sse.onerror=()=>{lg('\u2715 Connection lost.',true);btn.disabled=false;$('status-dot').className='status-dot inactive';};
    }).catch(e=>{lg('\u2715 '+e.message,true);btn.disabled=false;});
}
window.addEventListener('resize',drawTL);
$('url-input').addEventListener('keydown',e=>{if(e.key==='Enter')run();});
</script>
</body></html>"""

if __name__=="__main__":
    app.run(debug=False,host=CFG.host,port=CFG.port,threaded=True)