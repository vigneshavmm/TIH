from flask import Flask, request, jsonify
import json, math, os, hashlib

try:
    import geopandas as gpd
except ImportError:
    gpd = None

app = Flask(__name__)

GRID  = [['F','C','9','8'],['J','3','2','7'],['K','4','5','6'],['L','M','P','T']]
CHARS = {c:(r,col) for r,row in enumerate(GRID) for col,c in enumerate(row)}
BOUNDS = {'lat':(2.5,38.5),'lon':(63.5,99.5)}

NALLAMALA_SHP_PATH = r"C:\Users\Vignesh\Desktop\vignesh\TIH\data\vectorfiles\Nallamala_boundary\Nallamala_boundary.shp"
INDIA_SHP_PATH     = r"C:\Users\Vignesh\Desktop\vignesh\TIH\data\vectorfiles\INDIA_Boundary\INDIA_Boundary.shp"

def _load_geojson(path):
    try:
        return json.loads(gpd.read_file(path).to_crs(epsg=4326).to_json())
    except Exception as e:
        print(f"[WARN] {path}: {e}"); return None

NALLAMALA_GEOJSON = _load_geojson(NALLAMALA_SHP_PATH) if gpd else None
INDIA_GEOJSON     = _load_geojson(INDIA_SHP_PATH)     if gpd else None

# ── DIGIPIN ───────────────────────────────────────────────────
def encode_digipin(lat, lon, precision=10):
    la0,la1 = BOUNDS['lat']; lo0,lo1 = BOUNDS['lon']
    if not (la0<=lat<=la1 and lo0<=lon<=lo1): return None
    code = ""
    for _ in range(precision):
        ls=(la1-la0)/4; cs=(lo1-lo0)/4
        r=min(3,int((la1-lat)/ls)); c=min(3,int((lon-lo0)/cs))
        code += GRID[r][c]
        la1=la1-r*ls; la0=la1-ls; lo0=lo0+c*cs; lo1=lo0+cs
    return code

def decode_digipin(dp):
    dp=dp.replace('-','').upper().strip()
    if not dp or not all(c in CHARS for c in dp): return None
    la0,la1=BOUNDS['lat']; lo0,lo1=BOUNDS['lon']
    for ch in dp:
        r,c=CHARS[ch]; ls=(la1-la0)/4; cs=(lo1-lo0)/4
        la1=la1-r*ls; la0=la1-ls; lo0=lo0+c*cs; lo1=lo0+cs
    clat=(la0+la1)/2; clon=(lo0+lo1)/2
    lm=(la1-la0)*111320; cm=(lo1-lo0)*111320*math.cos(math.radians(clat))
    return {"center_lat":round(clat,8),"center_lon":round(clon,8),
            "lat_min":round(la0,8),"lat_max":round(la1,8),
            "lon_min":round(lo0,8),"lon_max":round(lo1,8),
            "length":len(dp),"cell_lat_m":round(lm,2),
            "cell_lon_m":round(cm,2),"area_m2":round(lm*cm,2)}

def get_digipin_grid_cells(la0,la1,lo0,lo1,precision=6):
    lr=(BOUNDS['lat'][1]-BOUNDS['lat'][0])/(4**precision)
    lc=(BOUNDS['lon'][1]-BOUNDS['lon'][0])/(4**precision)
    cells=[]; lat=la0
    while lat<la1:
        lon=lo0
        while lon<lo1:
            dp=encode_digipin(lat+lr/2,lon+lc/2,precision)
            if dp:
                d=decode_digipin(dp)
                if d: cells.append({k:d[k] for k in ("digipin" if False else None, *["lat_min","lat_max","lon_min","lon_max","center_lat","center_lon"])} if False else {**{k:d[k] for k in ["lat_min","lat_max","lon_min","lon_max","center_lat","center_lon"]},"digipin":dp})
            lon+=lc
        lat+=lr
    return cells

# ── RNG ───────────────────────────────────────────────────────
def _rng(seed):
    s=int(hashlib.md5(str(seed).encode()).hexdigest(),16)%(2**31)
    def rand():
        nonlocal s; s=(s*1664525+1013904223)&0xFFFFFFFF; return s/0xFFFFFFFF
    return rand

# ── LULC ──────────────────────────────────────────────────────
def get_lulc_matrix(lat,lon):
    rand=_rng(f"{lat:.3f}{lon:.3f}")
    f=max(0.25,1.0-math.sqrt((lat-15.8)**2+(lon-79.3)**2)*0.14)
    B=[[39500,1800,320,80,40],[1200,27500,3100,550,180],[180,2600,14500,2300,750],
       [60,350,1700,21000,1100],[15,80,520,1400,9800]]
    return [[max(0,int(v*f*(1+(rand()-0.5)*0.28))) for v in row] for row in B]

def get_lulc_timeseries(lat,lon):
    rand=_rng(f"{lat:.3f}{lon:.3f}ts")
    vf=max(0.1,1.0-math.sqrt((lat-15.8)**2+(lon-79.3)**2)*0.18)
    years=[1991,2001,2011,2021]
    cls=['Vegetation','Crop Land','Scrub Land','Urban Area','Rural Area','Aquaculture','Pond/Lake','Open Land']
    col=['#2d8a3e','#d4e157','#8bc34a','#e53935','#ff8f00','#00acc1','#1565c0','#f48fb1']
    b=[55*vf,18,10,3*(1-vf+0.2),5,2,4,3]
    result={}
    for yi,yr in enumerate(years):
        t=yi/3.0; rv=rand()
        row=[]
        for ci,c in enumerate(cls):
            v=b[ci]
            if c=='Vegetation':   v*=(1-t*0.42*(1+rv*0.2))
            elif c=='Crop Land':  v*=(1+t*0.85*(1+rand()*0.3))
            elif c=='Scrub Land': v*=(1-t*0.35*rand())
            elif c=='Urban Area': v*=(1+t*3.2*(1+rand()*0.5))
            elif c=='Rural Area': v*=(1+t*1.1)
            elif c=='Aquaculture':v*=(1+t*0.6*rand())
            elif c=='Open Land':  v*=(1+t*0.4*rand())
            row.append(round(max(0.5,v*(1+(rand()-0.5)*0.15)),2))
        tot=sum(row); row=[round(v/tot*100,2) for v in row]; result[yr]=row
    return {"years":years,"classes":cls,"colors":col,"data":result}

# ── CHANGE DETECTION ─────────────────────────────────────────
def get_cell_pixel_changes(lat,lon,fy,ty):
    N=20; rand=_rng(f"{lat:.3f}{lon:.3f}{fy}{ty}")
    dist=math.sqrt((lat-15.8)**2+(lon-79.3)**2)
    vb=max(0.05,1.0-dist*0.18); td=(ty-fy)/30.0
    pixels=[]
    for row in range(N):
        pr=[]
        for col in range(N):
            r1=rand(); ef=min(row,N-1-row,col,N-1-col)/(N/2)
            vp=vb*(0.6+ef*0.4)
            w=[vp*0.55,vp*0.25,vp*0.10,(1-vp)*0.50,(1-vp)*0.25,0.04,(1-vp)*0.06]
            cum=0; t1=0
            for i,ww in enumerate(w):
                cum+=ww
                if r1<cum: t1=i; break
            r2=rand(); dp2=td*0.35*(1-ef*0.5)*(1+rand()*0.3)
            if t1==0: tw=[max(0,0.72-dp2),dp2*0.30,dp2*0.20,dp2*0.30,dp2*0.05,0.01,dp2*0.15]
            elif t1==1: tw=[td*0.08,max(0,0.60-dp2),dp2*0.25,dp2*0.35,dp2*0.10,0.01,dp2*0.10]
            elif t1==2: tw=[td*0.04,td*0.12,max(0,0.55-dp2*0.5),0.20+dp2*0.2,0.08,0.01,0.05+dp2*0.05]
            elif t1==3: tw=[0.01,0.03,0.04,0.70,0.05,0.01,0.10+td*0.06]
            elif t1==4: tw=[0.01,0.05,0.12,0.35,0.38,0.01,0.08]
            elif t1==5: tw=[0.01,0.02,0.04,0.15,0.08,0.65,0.05]
            else:       tw=[0.00,0.01,0.02,0.08,0.05,0.01,0.83]
            tot=sum(tw); cum=0; t2=t1
            for i,ww in enumerate(tw):
                cum+=ww/tot
                if r2<cum: t2=i; break
            pr.append({"t1":t1,"t2":t2})
        pixels.append(pr)
    return pixels

# ── HOTSPOTS ─────────────────────────────────────────────────
def get_hotspots(lat,lon,fy=2001,ty=2021):
    LA0,LA1,LO0,LO1=14.6,17.0,78.2,80.4; STEP=0.18; NP=12
    CLAT,CLON=15.8,79.3; td=(ty-fy)/30.0
    colors={'CRITICAL':'#ef4444','HIGH':'#f97316','MODERATE':'#eab308','LOW':'#22c55e'}
    radii={'CRITICAL':16,'HIGH':12,'MODERATE':9,'LOW':7}
    DL={'forest_loss':'Forest cover loss detected','agri_encr':'Agricultural encroachment',
        'urban_pressure':'Urban expansion pressure','degradation':'Canopy degradation (dense→open)',
        'edge_effect':'Boundary edge vulnerability','stable':'Forest cover stable — monitor'}
    results=[]; g=LA0
    while g<=LA1:
        gl=LO0
        while gl<=LO1:
            dist=math.sqrt((g-CLAT)**2+(gl-CLON)**2)
            if dist>1.8: gl+=STEP; continue
            ef=min(1.0,dist/1.4); vb=max(0.08,1.0-dist*0.28)
            pr=_rng(f"{g:.3f}{gl:.3f}{fy}{ty}score")
            cnt={'f00':0,'f03':0,'f06':0,'f01':0,'total':0,'ft':0}
            for ri in range(NP):
                for ci in range(NP):
                    rpx=pr(); ep=min(ri,NP-1-ri,ci,NP-1-ci)/(NP/2)
                    vp=min(0.95,vb*(0.5+ep*0.5))
                    w1=[vp*(0.55-td*0.15),vp*(0.25-td*0.05),vp*0.10,
                        (1-vp)*(0.50+td*0.15),(1-vp)*0.20,0.04,(1-vp)*(0.05+td*0.10)]
                    w1=[max(0,x) for x in w1]; s1=sum(w1); cum=0; t1=0
                    for i,ww in enumerate(w1):
                        cum+=ww/s1
                        if rpx<cum: t1=i; break
                    rpx2=pr(); dp_=td*0.38*(0.5+ef*0.5)*(1+pr()*0.3)
                    if t1 in(0,1): w2=[max(0,0.72-dp_),dp_*0.28,dp_*0.18,dp_*0.32,dp_*0.06,0.01,dp_*0.14]
                    elif t1==2:    w2=[0.03,0.10,max(0,0.55-dp_*0.4),0.20+dp_*0.15,0.08,0.01,0.03+dp_*0.05]
                    elif t1==3:    w2=[0.01,0.02,0.04,0.72,0.05,0.01,0.10+td*0.05]
                    else:          w2=[0.01,0.03,0.06,0.20,0.30,0.08,0.32]
                    s2=sum(w2); cum=0; t2=t1
                    for i,ww in enumerate(w2):
                        cum+=ww/s2
                        if rpx2<cum: t2=i; break
                    cnt['total']+=1
                    if t1 in(0,1): cnt['ft']+=1
                    if t1 in(0,1) and t2>1:  cnt['f00']+=1
                    if t1 in(0,1) and t2==3: cnt['f03']+=1
                    if t1 in(0,1) and t2==6: cnt['f06']+=1
                    if t1==0 and t2==1:       cnt['f01']+=1
            tot=max(1,cnt['total']); ft=max(1,cnt['ft'])
            flr=cnt['f00']/tot; ar=cnt['f03']/tot; ur=cnt['f06']/tot
            dr=cnt['f01']/ft;   es=ef*0.35
            sc=min(1.0,flr*0.38+ar*0.22+ur*0.18+dr*0.12+es*0.10)
            risk='CRITICAL' if sc>=0.60 else 'HIGH' if sc>=0.42 else 'MODERATE' if sc>=0.26 else 'LOW'
            ds={'forest_loss':flr*0.38,'agri_encr':ar*0.22,'urban_pressure':ur*0.18,
                'degradation':dr*0.12,'edge_effect':es*0.10}
            if sc<0.15: ds={'stable':0.5}
            top=sorted(ds,key=ds.get,reverse=True)[:2]
            jr=_rng(f"{g:.2f}{gl:.2f}jit")
            results.append({'lat':round(g+(jr()-0.5)*STEP*0.35,5),'lon':round(gl+(jr()-0.5)*STEP*0.35,5),
                'risk':risk,'color':colors[risk],'radius':radii[risk],'score':round(sc,3),
                'score_pct':f"{sc*100:.1f}%",'drivers':' · '.join(DL[d] for d in top),
                'forest_loss_pct':f"{flr*100:.1f}%",'agri_encr_pct':f"{ar*100:.1f}%",
                'urban_press_pct':f"{ur*100:.1f}%",'degradation_pct':f"{dr*100:.1f}%",
                'digipin':encode_digipin(g,gl,6) or '—'})
            gl+=STEP
        g+=STEP
    results.sort(key=lambda x:x['score'],reverse=True)
    return results[:28]

# ── ENCROACHMENT ─────────────────────────────────────────────
ENC_TYPES={
    'AGRICULTURE':        {'color':'#f59e0b','icon':'🌾','action':'Immediate survey + revenue boundary verification'},
    'CONSTRUCTION':       {'color':'#ef4444','icon':'🏗️','action':'FIR + demolition notice within 48h'},
    'LOGGING':            {'color':'#a16207','icon':'🪵','action':'Seizure of equipment + forest case registration'},
    'MINING':             {'color':'#7c3aed','icon':'⛏️','action':'CPCB/SPCB joint inspection + mining lease audit'},
    'NATURAL_DISTURBANCE':{'color':'#22c55e','icon':'🌿','action':'Monitor only — no enforcement required'},
}
SEV_T={'ACTIVE':0.60,'WARNING':0.38,'WATCH':0.18}

def _spectral_proxies(lat,lon,fy,ty):
    rand=_rng(f"{lat:.3f}{lon:.3f}{fy}{ty}enc")
    dist=math.sqrt((lat-15.8)**2+(lon-79.3)**2)
    td=(ty-fy)/30.0; vg=max(0.05,1.0-dist*0.22)
    nt1=vg*(0.85+rand()*0.15); nd=td*(0.18+rand()*0.25)*(1-vg*0.4)
    nt2=max(0.02,nt1-nd); nv=nd/max(1,ty-fy)*10
    tx=(0.15+rand()*0.85)*(1-vg*0.6)
    pl=rand()*(1-vg*0.5); pc=rand()*(0.4+vg*0.3); pp=rand()*(1-vg*0.7)
    bs=min(1.0,max(0,nd*1.4+tx*0.3-0.1+rand()*0.15))
    vel=1300*(1-vg*0.2)*nd/max(1,ty-fy)
    return {'ndvi_t1':round(nt1,3),'ndvi_t2':round(nt2,3),'ndvi_drop':round(nd,3),
            'ndvi_vel':round(nv,3),'texture':round(tx,3),'pattern_linear':round(pl,3),
            'pattern_cluster':round(pc,3),'pattern_point':round(pp,3),
            'bare_soil':round(bs,3),'velocity_ha_yr':round(vel,1)}

def classify_encroachment(lat,lon,fy,ty):
    p=_spectral_proxies(lat,lon,fy,ty)
    bs,tx,pl,pc,pp,nd=p['bare_soil'],p['texture'],p['pattern_linear'],p['pattern_cluster'],p['pattern_point'],p['ndvi_drop']
    if bs>0.45 and tx>0.52:               et='CONSTRUCTION'; cf=(bs+tx)/2
    elif bs>0.38 and pl>max(pc,pp)*1.2:   et='LOGGING';      cf=bs*0.5+pl*0.5
    elif pp>0.55 and bs>0.48:             et='MINING';       cf=(pp+bs)/2
    elif nd>0.12 and pc>max(pl,pp):       et='AGRICULTURE';  cf=nd*0.6+pc*0.4
    else:                                  et='NATURAL_DISTURBANCE'; cf=max(0.1,1.0-bs-nd*0.5)
    cs=nd*0.5+bs*0.3+tx*0.2
    sev='ACTIVE' if cs>=SEV_T['ACTIVE'] else 'WARNING' if cs>=SEV_T['WARNING'] else 'WATCH' if cs>=SEV_T['WATCH'] else 'STABLE'
    m=ENC_TYPES[et]
    return {'type':et,'color':m['color'],'icon':m['icon'],'severity':sev,
            'confidence':round(min(0.99,cf),3),'confidence_pct':f"{min(99,cf*100):.1f}%",
            'action':m['action'],'ndvi_t1_pct':f"{p['ndvi_t1']*100:.1f}%",
            'ndvi_t2_pct':f"{p['ndvi_t2']*100:.1f}%",'ndvi_drop_pct':f"{p['ndvi_drop']*100:.1f}%",
            'texture_score':f"{p['texture']*100:.1f}%",'bare_soil_pct':f"{p['bare_soil']*100:.1f}%",
            'velocity_ha_yr':p['velocity_ha_yr'],'change_score':round(cs,3)}

def get_encroachment_alerts(fy,ty):
    LA0,LA1,LO0,LO1=14.7,16.9,78.3,80.3; STEP=0.20
    alerts=[]; n=1; g=LA0
    while g<=LA1:
        gl=LO0
        while gl<=LO1:
            if math.sqrt((g-15.8)**2+(gl-79.3)**2)>1.7: gl+=STEP; continue
            cls=classify_encroachment(g,gl,fy,ty)
            if cls['severity']=='STABLE': gl+=STEP; continue
            rng=_rng(f"{g:.2f}{gl:.2f}jit")
            lf=round(g+(rng()-0.5)*STEP*0.4,5); lnf=round(gl+(rng()-0.5)*STEP*0.4,5)
            dp=encode_digipin(lf,lnf,6) or '—'
            ah=round(cls['velocity_ha_yr']*(ty-fy),1)
            day=(int(hashlib.md5(dp.encode()).hexdigest(),16)%28)+1
            mon=(int(hashlib.md5((dp+'m').encode()).hexdigest(),16)%12)+1
            alerts.append({'alert_id':f"AP-FOR-{ty}-{n:04d}",'digipin':dp,'lat':lf,'lon':lnf,
                'type':cls['type'],'color':cls['color'],'icon':cls['icon'],
                'severity':cls['severity'],'confidence':cls['confidence'],
                'confidence_pct':cls['confidence_pct'],'area_ha':ah,
                'velocity_ha_yr':cls['velocity_ha_yr'],'action':cls['action'],
                'detected_date':f"{ty}-{mon:02d}-{day:02d}",
                'evidence':{'ndvi_before':cls['ndvi_t1_pct'],'ndvi_after':cls['ndvi_t2_pct'],
                    'ndvi_drop':cls['ndvi_drop_pct'],'bare_soil':cls['bare_soil_pct'],
                    'texture':cls['texture_score'],'change_score':cls['change_score']}})
            n+=1; gl+=STEP
        g+=STEP
    SO={'ACTIVE':0,'WARNING':1,'WATCH':2}
    alerts.sort(key=lambda x:(SO[x['severity']],-x['confidence']))
    return alerts

# ── HTML ─────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Forest Intelligence · Nallamala · DIGIPIN v8</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet"/>
<style>
:root{--ink:#0b0f14;--surface:#0f1822;--panel:#111d2b;--border:#1a2f45;--border2:#243d56;
  --accent:#00d4aa;--accent2:#3b82f6;--warn:#f59e0b;--danger:#ef4444;
  --text:#c8daea;--muted:#4a6d8a;--mono:'JetBrains Mono',monospace;--serif:'Instrument Serif',serif}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden;background:var(--ink)}
body{display:flex;flex-direction:column;font-family:var(--mono);color:var(--text);font-size:11px}
#topbar{height:52px;flex-shrink:0;background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 16px;gap:14px;position:relative;z-index:1000}
#topbar::after{content:'';position:absolute;bottom:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.4}
.logo-block{display:flex;align-items:center;gap:10px;flex-shrink:0}
.logo-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 10px var(--accent);animation:blink 2.4s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
.logo-title{font-family:var(--serif);font-style:italic;font-size:1.15rem;color:#fff;letter-spacing:.3px}
.logo-sub{font-size:.55rem;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-top:1px}
.vsep{width:1px;height:28px;background:var(--border);flex-shrink:0}
.search-wrap{display:flex;align-items:center;gap:5px}
#searchInput{background:var(--ink);border:1px solid var(--border);color:var(--text);
  padding:5px 10px;border-radius:4px;font-family:var(--mono);font-size:.62rem;
  width:210px;outline:none;letter-spacing:.5px}
#searchInput:focus{border-color:var(--accent)}
.btn{border:none;padding:5px 13px;border-radius:4px;font-family:var(--mono);
  font-size:.6rem;font-weight:600;cursor:pointer;letter-spacing:1px;transition:.12s;text-transform:uppercase}
.btn-g{background:var(--accent);color:#000}.btn-g:hover{filter:brightness(1.15)}
.btn-b{background:var(--accent2);color:#fff}.btn-b:hover{filter:brightness(1.2)}
.err-msg{font-size:.58rem;color:var(--danger);display:none;white-space:nowrap}
.date-group{display:flex;align-items:center;gap:5px;margin-left:4px}
.date-group label{font-size:.55rem;color:var(--muted);letter-spacing:1px}
input[type=date]{background:var(--ink);border:1px solid var(--border);color:var(--text);
  padding:4px 6px;border-radius:3px;font-family:var(--mono);font-size:.58rem;outline:none;color-scheme:dark}
input[type=date]:focus{border-color:var(--accent2)}
.sat-select{margin-left:auto;display:flex;align-items:center;gap:5px}
.sat-select label{font-size:.55rem;color:var(--muted);letter-spacing:1px}
select#satSource{background:var(--ink);border:1px solid var(--border);color:var(--accent);
  padding:4px 8px;border-radius:3px;font-family:var(--mono);font-size:.6rem;outline:none;cursor:pointer}
.chip{padding:2px 8px;border-radius:2px;font-size:.55rem;letter-spacing:1px;font-weight:600;border:1px solid;flex-shrink:0}
.chip-live{background:rgba(0,212,170,.1);border-color:var(--accent);color:var(--accent)}
.chip-loc{background:rgba(59,130,246,.1);border-color:var(--accent2);color:var(--accent2)}
#grid{flex:1;display:grid;grid-template-columns:1fr 1fr 1fr;grid-template-rows:1fr 1fr;
  gap:3px;padding:3px;overflow:hidden;background:var(--ink)}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:5px;
  display:flex;flex-direction:column;overflow:hidden;min-height:0;position:relative}
.panel:hover{border-color:var(--border2)}
.panel-head{height:30px;flex-shrink:0;padding:0 10px;display:flex;align-items:center;gap:7px;
  border-bottom:1px solid var(--border);background:rgba(11,15,20,.6)}
.ph-num{font-size:.52rem;color:var(--muted);letter-spacing:1px;padding:1px 5px;border:1px solid var(--border);border-radius:2px}
.ph-title{font-size:.6rem;color:var(--text);letter-spacing:1.5px;text-transform:uppercase;font-weight:600}
.ph-tag{font-size:.55rem;color:var(--accent);font-family:var(--mono);letter-spacing:.5px;
  max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-left:auto}
.panel-head .ph-tag~.expand-btn{margin-left:6px}
.ph-sat{margin-left:auto;display:flex;align-items:center;gap:6px}
.ph-sat span{font-size:.53rem;color:var(--muted)}
.ph-sat select{background:rgba(11,15,20,.8);border:1px solid var(--border2);color:var(--accent2);
  padding:2px 5px;border-radius:2px;font-family:var(--mono);font-size:.52rem;outline:none;cursor:pointer}
.ph-sat input[type=date]{font-size:.52rem;padding:2px 4px}
.pbody{flex:1;position:relative;overflow:hidden;min-height:0}
.mwrap{width:100%;height:100%}
.map-ctrl{position:absolute;top:7px;left:7px;z-index:500;display:flex;flex-direction:column;gap:2px}
.mc-btn{background:rgba(11,15,20,.92);border:1px solid var(--border);color:var(--muted);
  padding:3px 8px;border-radius:3px;font-family:var(--mono);font-size:.5rem;
  cursor:pointer;transition:.1s;white-space:nowrap;letter-spacing:.5px}
.mc-btn:hover,.mc-btn.on{border-color:var(--accent);color:var(--accent)}
#dp-badge{position:absolute;top:7px;left:50%;transform:translateX(-50%);
  background:rgba(11,15,20,.97);border:1px solid var(--accent);padding:3px 12px;
  border-radius:3px;font-family:var(--mono);font-size:.82rem;font-weight:700;
  color:var(--accent);letter-spacing:4px;z-index:700;display:none;pointer-events:none;white-space:nowrap}
#cinfo{position:absolute;bottom:7px;left:7px;z-index:600;background:rgba(11,15,20,.95);
  border:1px solid var(--border);padding:6px 10px;border-radius:4px;display:none;min-width:140px}
.ci-row{display:flex;justify-content:space-between;gap:12px;font-size:.54rem;line-height:2;border-bottom:1px solid var(--border)}
.ci-row:last-child{border-bottom:none}
.ci-k{color:var(--muted);letter-spacing:.5px}.ci-v{color:var(--accent);font-weight:600}
#lulc-ctrl{position:absolute;top:7px;left:7px;z-index:600;background:rgba(11,15,20,.95);
  border:1px solid var(--border);border-radius:4px;display:flex;flex-direction:column;gap:0;overflow:hidden}
.lulc-year-btn{background:transparent;border:none;border-bottom:1px solid var(--border);
  color:var(--muted);padding:4px 14px;font-family:var(--mono);font-size:.58rem;
  cursor:pointer;letter-spacing:1.5px;text-align:left;transition:.1s}
.lulc-year-btn:last-child{border-bottom:none}
.lulc-year-btn:hover,.lulc-year-btn.active{background:rgba(0,212,170,.1);color:var(--accent)}
#lulc-legend{position:absolute;bottom:7px;left:7px;z-index:600;background:rgba(11,15,20,.95);
  border:1px solid var(--border);padding:6px 9px;border-radius:4px;font-size:.52rem}
.ll-row{display:flex;align-items:center;gap:5px;margin-bottom:2px}
.ll-row:last-child{margin-bottom:0}
.ll-swatch{width:10px;height:10px;border-radius:1px;flex-shrink:0}
#lulc-popup{position:absolute;z-index:900;background:rgba(11,15,20,.98);border:1px solid var(--border2);
  border-radius:5px;padding:10px 12px;min-width:220px;display:none;pointer-events:none;box-shadow:0 4px 20px rgba(0,0,0,.5)}
#lulc-popup .lp-title{font-size:.58rem;color:var(--accent);letter-spacing:2px;margin-bottom:6px}
#lulc-popup .lp-dp{font-size:.52rem;color:var(--muted);margin-bottom:6px;letter-spacing:1px}
#lulc-chart{display:block}
.grid-tag{position:absolute;top:7px;right:7px;z-index:600;background:rgba(11,15,20,.9);
  border:1px solid var(--border);padding:3px 8px;border-radius:3px;font-size:.5rem;color:var(--muted);letter-spacing:.5px}
#cd-legend{position:absolute;bottom:7px;left:7px;z-index:600;background:rgba(11,15,20,.97);
  border:1px solid var(--border);padding:7px 10px;border-radius:4px;font-size:.52rem;min-width:155px}
#cd-legend .cd-title{color:var(--muted);letter-spacing:1px;margin-bottom:5px;font-size:.48rem;text-transform:uppercase}
.cd-row{display:flex;align-items:center;gap:6px;margin-bottom:3px;line-height:1.4}
.cd-row:last-child{margin-bottom:0}
.cd-sw{width:12px;height:10px;border-radius:1px;flex-shrink:0}
.cd-label{color:var(--text);font-size:.5rem}
#cd-stats{position:absolute;top:7px;right:7px;z-index:600;background:rgba(11,15,20,.97);
  border:1px solid var(--border);padding:6px 9px;border-radius:4px;font-size:.52rem;line-height:2;min-width:130px}
#cd-stats .cds-title{color:var(--muted);font-size:.48rem;letter-spacing:1px;margin-bottom:3px}
.cds-row{display:flex;justify-content:space-between;gap:8px}
.cds-k{color:var(--muted)}.cds-v{font-weight:700}
#cd-period{position:absolute;top:7px;left:50%;transform:translateX(-50%);z-index:600;
  background:rgba(11,15,20,.95);border:1px solid var(--border2);padding:3px 10px;
  border-radius:3px;font-size:.55rem;color:var(--accent2);letter-spacing:1px;white-space:nowrap;pointer-events:none}
#cd-canvas-container{position:absolute;inset:0;z-index:400;pointer-events:none;overflow:hidden}
#cd-canvas{position:absolute;top:0;left:0;pointer-events:none}
#cd-loading{position:absolute;inset:0;z-index:700;background:rgba(11,15,20,.7);display:flex;
  align-items:center;justify-content:center;font-size:.6rem;color:var(--accent);letter-spacing:2px;pointer-events:none}
.sk-init{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:8px;font-size:.6rem;color:var(--muted);pointer-events:none;letter-spacing:1px}
.sk-tip{position:absolute;background:rgba(11,15,20,.97);border:1px solid var(--border);
  padding:5px 9px;border-radius:3px;font-size:.56rem;line-height:1.9;display:none;
  z-index:900;pointer-events:none;white-space:nowrap;font-family:var(--mono)}
.metric-strip{display:flex;align-items:stretch;border-bottom:1px solid var(--border);flex-shrink:0;overflow:hidden}
.metric{flex:1;padding:5px 8px;border-right:1px solid var(--border);display:flex;flex-direction:column;justify-content:center}
.metric:last-child{border-right:none}
.metric-val{font-size:.95rem;font-weight:700;color:var(--accent);letter-spacing:-.5px}
.metric-val.warn{color:var(--warn)}.metric-val.danger{color:var(--danger)}
.metric-lbl{font-size:.47rem;color:var(--muted);letter-spacing:1px;margin-top:1px}
.source-label{flex-shrink:0;padding:3px 10px;border-top:1px solid var(--border);
  font-size:.48rem;color:var(--muted);letter-spacing:.5px;background:rgba(11,15,20,.4)}
.expand-btn{margin-left:auto;background:transparent;border:1px solid var(--border);color:var(--muted);
  width:22px;height:22px;border-radius:3px;cursor:pointer;display:flex;align-items:center;
  justify-content:center;font-size:10px;transition:.12s;flex-shrink:0;padding:0}
.expand-btn:hover{border-color:var(--accent);color:var(--accent);background:rgba(0,212,170,.07)}
.expand-btn svg{pointer-events:none}
.panel-head .ph-tag{margin-left:auto}
.panel-head .expand-btn{margin-left:6px}
#fv-overlay{position:fixed;inset:0;z-index:9000;background:rgba(5,8,13,.97);
  display:none;flex-direction:column;animation:fvIn .18s ease-out}
#fv-overlay.active{display:flex}
@keyframes fvIn{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:scale(1)}}
#fv-topbar{height:48px;flex-shrink:0;background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 16px;gap:12px;position:relative}
#fv-topbar::after{content:'';position:absolute;bottom:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.5}
#fv-num{font-size:.52rem;color:var(--muted);letter-spacing:1px;padding:2px 7px;border:1px solid var(--border);border-radius:2px}
#fv-title{font-size:.72rem;color:#fff;letter-spacing:2px;text-transform:uppercase;font-weight:600}
#fv-tag{font-size:.55rem;color:var(--accent);letter-spacing:.5px}
#fv-tools{margin-left:auto;display:flex;align-items:center;gap:8px}
#fv-close{background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4);color:#ef4444;
  padding:4px 14px;border-radius:3px;font-family:var(--mono);font-size:.6rem;font-weight:700;
  cursor:pointer;letter-spacing:2px;transition:.12s}
#fv-close:hover{background:rgba(239,68,68,.25);border-color:#ef4444}
#fv-body{flex:1;position:relative;overflow:hidden;min-height:0}
#fv-map-wrap{width:100%;height:100%}
#fv-graph-wrap{width:100%;height:100%;display:flex;flex-direction:column;overflow:hidden}
#fv-graph-header{flex-shrink:0;padding:10px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px}
#fv-graph-body{flex:1;position:relative;overflow:hidden;min-height:0}
#fv-sk-tip{position:absolute;background:rgba(11,15,20,.97);border:1px solid var(--border);
  padding:5px 9px;border-radius:3px;font-size:.6rem;line-height:2;display:none;
  z-index:900;pointer-events:none;white-space:nowrap;font-family:var(--mono)}
#fv-metrics{flex-shrink:0;display:flex;border-top:1px solid var(--border);background:rgba(11,15,20,.5)}
#fv-metrics .metric{padding:8px 16px;font-size:1rem}
#fv-metrics .metric-lbl{font-size:.52rem}
#fv-cd-canvas{position:absolute;top:0;left:0;pointer-events:none;display:none;z-index:450}
#fv-topbar::before{content:'ESC TO CLOSE';position:absolute;right:70px;bottom:8px;
  font-size:.42rem;color:var(--muted);letter-spacing:1.5px;opacity:.5}
.fv-mc-btn{background:rgba(11,15,20,.92);border:1px solid var(--border);color:var(--muted);
  padding:4px 10px;border-radius:3px;font-family:var(--mono);font-size:.55rem;cursor:pointer;transition:.1s;letter-spacing:.5px}
.fv-mc-btn:hover,.fv-mc-btn.on{border-color:var(--accent);color:var(--accent)}
.leaflet-control-zoom a{background:rgba(11,15,20,.9)!important;border-color:var(--border)!important;color:var(--text)!important}
.leaflet-control-zoom a:hover{border-color:var(--accent)!important;color:var(--accent)!important}
.leaflet-popup-content-wrapper{background:rgba(11,15,20,.97)!important;border:1px solid var(--border)!important;
  color:var(--text)!important;border-radius:4px!important;box-shadow:none!important}
.leaflet-popup-tip{background:var(--border)!important}
.leaflet-popup-content{font-family:var(--mono)!important;font-size:11px!important;margin:10px 12px!important}
.leaflet-tooltip{background:rgba(11,15,20,.95)!important;border:1px solid var(--border)!important;
  color:var(--text)!important;font-family:var(--mono)!important;font-size:10px!important}
</style>
</head>
<body>
<div id="topbar">
  <div class="logo-block">
    <div class="logo-dot"></div>
    <div>
      <div class="logo-title">Forest Intelligence</div>
      <div class="logo-sub">Nallamala · DIGIPIN v8 · Change Detection</div>
    </div>
  </div>
  <div class="vsep"></div>
  <div class="search-wrap">
    <input type="text" id="searchInput" placeholder="Place name or DIGIPIN code…"/>
    <button class="btn btn-g" onclick="doSearch()">SEARCH</button>
    <span id="search-err" class="err-msg"></span>
  </div>
  <div class="vsep"></div>
  <div class="date-group">
    <label>FROM</label><input type="date" id="d0" value="2001-01-01"/>
    <label>TO</label><input type="date" id="d1" value="2021-12-31"/>
  </div>
  <div class="sat-select">
    <label>SAT SOURCE</label>
    <select id="satSource" onchange="onSatSourceChange()">
      <option value="s2">Sentinel-2 (GIBS)</option>
      <option value="ls8">Landsat-8 (GIBS)</option>
      <option value="ls9">Landsat-9 (GIBS)</option>
    </select>
  </div>
  <button class="btn btn-b" onclick="doAnalyse()">ANALYSE</button>
  <div class="vsep"></div>
  <div class="chip chip-live">LIVE</div>
  <div class="chip chip-loc" id="loc-chip">14.8–16.8°N · 78.4–80.2°E</div>
</div>

<div id="grid">
  <!-- 01 -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-num">01</span><span class="ph-title">DIGIPIN Reference Map</span>
      <span class="ph-tag" id="t1">Nallamala Forest Reserve, AP · DIGIPIN Grid</span>
      <button class="expand-btn" onclick="openFullView(1)" title="Full view"><svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M1 4V1h3M7 1h3v3M10 7v3H7M4 10H1V7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
    <div class="pbody">
      <div id="m1" class="mwrap"></div>
      <div class="map-ctrl" id="bsw1">
        <button class="mc-btn on" onclick="switchBase('osm',event)">OSM</button>
        <button class="mc-btn" onclick="switchBase('terrain',event)">TERRAIN</button>
        <button class="mc-btn" onclick="switchBase('satellite',event)">SATELLITE</button>
        <button class="mc-btn" onclick="switchBase('carto',event)">CARTO</button>
      </div>
      <div id="dp-badge"></div>
      <div id="cinfo">
        <div class="ci-row"><span class="ci-k">DIGIPIN</span><span class="ci-v" id="ci-dp">—</span></div>
        <div class="ci-row"><span class="ci-k">LAT</span><span class="ci-v" id="ci-lat">—</span></div>
        <div class="ci-row"><span class="ci-k">LON</span><span class="ci-v" id="ci-lon">—</span></div>
        <div class="ci-row"><span class="ci-k">CELL</span><span class="ci-v" id="ci-cell">—</span></div>
        <div class="ci-row"><span class="ci-k">AREA</span><span class="ci-v" id="ci-area">—</span></div>
      </div>
      <div class="grid-tag" id="grid-tag-1">PREC-6 GRID</div>
    </div>
  </div>
  <!-- 02 -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-num">02</span><span class="ph-title">LULC Temporal Viewer · 1991–2021</span>
      <span class="ph-tag" id="t2">Click a cell to view class variation</span>
      <button class="expand-btn" onclick="openFullView(2)" title="Full view"><svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M1 4V1h3M7 1h3v3M10 7v3H7M4 10H1V7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
    <div class="pbody">
      <div id="m2" class="mwrap"></div>
      <div id="lulc-ctrl">
        <button class="lulc-year-btn active" onclick="setLulcYear(1991,this)">1991</button>
        <button class="lulc-year-btn" onclick="setLulcYear(2001,this)">2001</button>
        <button class="lulc-year-btn" onclick="setLulcYear(2011,this)">2011</button>
        <button class="lulc-year-btn" onclick="setLulcYear(2021,this)">2021</button>
      </div>
      <div id="lulc-legend">
        <div class="ll-row"><div class="ll-swatch" style="background:#2d8a3e"></div>Vegetation</div>
        <div class="ll-row"><div class="ll-swatch" style="background:#d4e157"></div>Crop Land</div>
        <div class="ll-row"><div class="ll-swatch" style="background:#8bc34a"></div>Scrub Land</div>
        <div class="ll-row"><div class="ll-swatch" style="background:#e53935"></div>Urban Area</div>
        <div class="ll-row"><div class="ll-swatch" style="background:#ff8f00"></div>Rural Area</div>
        <div class="ll-row"><div class="ll-swatch" style="background:#00acc1"></div>Aquaculture</div>
        <div class="ll-row"><div class="ll-swatch" style="background:#1565c0"></div>Pond/Lake</div>
        <div class="ll-row"><div class="ll-swatch" style="background:#f48fb1"></div>Open Land</div>
      </div>
      <div id="lulc-popup">
        <div class="lp-title">LULC CLASS VARIATION</div>
        <div class="lp-dp" id="lp-dp">—</div>
        <canvas id="lulc-chart" width="210" height="130"></canvas>
      </div>
    </div>
  </div>
  <!-- 03 -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-num">03</span><span class="ph-title" id="p3-title">Cell-Scale Satellite View</span>
      <div class="ph-sat">
        <span>DATE</span><input type="date" id="sat3-date" value="2023-11-01" onchange="buildCellSat()"/>
      </div>
      <button class="expand-btn" onclick="openFullView(3)" title="Full view"><svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M1 4V1h3M7 1h3v3M10 7v3H7M4 10H1V7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
    <div class="pbody">
      <div id="m3" class="mwrap"></div>
      <div id="scale-box">
        <canvas id="cell-canvas" width="80" height="80"></canvas>
        <div class="sv" id="cell-dims">Select a cell</div>
        <div class="sv2" id="cell-area">PREC-10 · ~4m</div>
      </div>
    </div>
  </div>
  <!-- 04 -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-num">04</span><span class="ph-title">Land Cover Transition · Sankey</span>
      <span class="ph-tag" id="t4">Click map → satellite date range drives analysis</span>
      <button class="expand-btn" onclick="openFullView(4)" title="Full view"><svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M1 4V1h3M7 1h3v3M10 7v3H7M4 10H1V7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
    <div class="metric-strip" id="metric-strip" style="display:none">
      <div class="metric"><div class="metric-val danger" id="m-defor">—</div><div class="metric-lbl">FOREST LOSS (ha)</div></div>
      <div class="metric"><div class="metric-val" id="m-stable">—</div><div class="metric-lbl">STABLE FOREST (ha)</div></div>
      <div class="metric"><div class="metric-val warn" id="m-encr">—</div><div class="metric-lbl">AGRI ENCROACH (ha)</div></div>
      <div class="metric"><div class="metric-val" id="m-regrow">—</div><div class="metric-lbl">REGROWTH (ha)</div></div>
    </div>
    <div class="pbody" id="sk-body">
      <div class="sk-init" id="sk-init">
        <svg width="32" height="32" viewBox="0 0 32 32"><circle cx="16" cy="16" r="14" stroke="#00d4aa" stroke-width="1.5" fill="none"/><path d="M10 16 L16 10 L22 16" stroke="#00d4aa" stroke-width="1.5" fill="none"/><path d="M16 10 L16 22" stroke="#00d4aa" stroke-width="1.5"/></svg>
        CLICK MAP TO LOAD ANALYSIS
      </div>
      <svg id="sk-svg" style="display:block"></svg>
      <div class="sk-tip" id="sk-tip"></div>
    </div>
    <div class="source-label" id="sk-source" style="display:none">SOURCE · Sentinel-2 / Landsat-8/9 · NASA GIBS · LULC derived from satellite spectral analysis</div>
  </div>
  <!-- 05 -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-num">05</span><span class="ph-title">Change Detection Map</span>
      <span class="ph-tag" id="t5">FROM → TO class transitions per pixel</span>
      <button class="expand-btn" onclick="openFullView(5)" title="Full view"><svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M1 4V1h3M7 1h3v3M10 7v3H7M4 10H1V7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
    <div class="pbody">
      <div id="m5" class="mwrap"></div>
      <div id="cd-canvas-container"><canvas id="cd-canvas"></canvas></div>
      <div id="cd-loading" style="display:none">RENDERING CHANGE DETECTION…</div>
      <div id="cd-period">— SELECT DATES AND CLICK ANALYSE —</div>
      <div id="cd-legend">
        <div class="cd-title">CHANGE TYPE</div>
        <div class="cd-row"><div class="cd-sw" style="background:#1a5c2a"></div><span class="cd-label">Stable Forest</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#dc2626"></div><span class="cd-label">Forest → Agriculture</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#7f1d1d"></div><span class="cd-label">Forest → Urban</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#ea580c"></div><span class="cd-label">Forest → Scrub/Bare</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#2563eb"></div><span class="cd-label">Non-Forest → Forest</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#f59e0b"></div><span class="cd-label">Agri → Urban</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#d4e157"></div><span class="cd-label">Stable Agriculture</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#a21caf"></div><span class="cd-label">Urban (Persistent)</span></div>
        <div class="cd-row"><div class="cd-sw" style="background:#374151"></div><span class="cd-label">No Significant Change</span></div>
      </div>
      <div id="cd-stats">
        <div class="cds-title">CHANGE STATS</div>
        <div class="cds-row"><span class="cds-k">Stable Forest</span><span class="cds-v" id="cds-stable" style="color:#1a5c2a">—</span></div>
        <div class="cds-row"><span class="cds-k">Forest Loss</span><span class="cds-v" id="cds-loss" style="color:#dc2626">—</span></div>
        <div class="cds-row"><span class="cds-k">Forest Gain</span><span class="cds-v" id="cds-gain" style="color:#2563eb">—</span></div>
        <div class="cds-row"><span class="cds-k">Urban Expand</span><span class="cds-v" id="cds-urban" style="color:#f59e0b">—</span></div>
        <div class="cds-row"><span class="cds-k">Dominant</span><span class="cds-v" id="cds-dom" style="color:#c8daea">—</span></div>
      </div>
    </div>
  </div>
  <!-- 06 -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-num">06</span><span class="ph-title">Encroachment Alerts</span>
      <span class="ph-tag" id="t6">AI-classified · spectral + spatial evidence</span>
      <button class="expand-btn" onclick="openFullView(6)" title="Full view"><svg width="11" height="11" viewBox="0 0 11 11" fill="none"><path d="M1 4V1h3M7 1h3v3M10 7v3H7M4 10H1V7" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
    </div>
    <div class="pbody">
      <div id="m6" class="mwrap"></div>
      <div id="enc-counts" style="display:none;position:absolute;top:7px;left:7px;z-index:600;background:rgba(11,15,20,.97);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:.52rem">
        <div style="color:var(--muted);font-size:.46rem;letter-spacing:1px;margin-bottom:5px;text-transform:uppercase">ALERT STATUS</div>
        <div style="display:flex;align-items:center;gap:5px;margin-bottom:4px"><div style="width:8px;height:8px;border-radius:1px;background:#ef4444"></div><span style="color:var(--muted);font-size:.48rem;width:52px">ACTIVE</span><span style="font-weight:700;color:#ef4444" id="enc-active">0</span></div>
        <div style="display:flex;align-items:center;gap:5px;margin-bottom:4px"><div style="width:8px;height:8px;border-radius:1px;background:#f97316"></div><span style="color:var(--muted);font-size:.48rem;width:52px">WARNING</span><span style="font-weight:700;color:#f97316" id="enc-warning">0</span></div>
        <div style="display:flex;align-items:center;gap:5px"><div style="width:8px;height:8px;border-radius:1px;background:#eab308"></div><span style="color:var(--muted);font-size:.48rem;width:52px">WATCH</span><span style="font-weight:700;color:#eab308" id="enc-watch">0</span></div>
      </div>
      <div id="enc-summary" style="display:none;position:absolute;bottom:7px;left:7px;z-index:600;background:rgba(11,15,20,.97);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:.52rem;min-width:148px">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px"><span style="color:var(--muted)">Total Area</span><span style="font-weight:700;color:var(--danger)" id="enc-total-ha">—</span></div>
        <div style="display:flex;justify-content:space-between;margin-bottom:3px"><span style="color:var(--muted)">Dominant</span><span style="font-weight:700;color:var(--warn)" id="enc-dominant">—</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Total Alerts</span><span style="font-weight:700" id="enc-total-count">—</span></div>
      </div>
      <div style="position:absolute;bottom:7px;right:7px;z-index:600;background:rgba(11,15,20,.92);border:1px solid var(--border);padding:6px 9px;border-radius:4px;font-size:.52rem">
        <div style="color:var(--muted);font-size:.46rem;letter-spacing:1px;margin-bottom:4px">TYPE</div>
        <div style="display:flex;align-items:center;gap:5px;margin-bottom:3px"><div style="width:8px;height:8px;border-radius:50%;background:#f59e0b"></div><span style="color:#f59e0b">Agriculture</span></div>
        <div style="display:flex;align-items:center;gap:5px;margin-bottom:3px"><div style="width:8px;height:8px;border-radius:50%;background:#ef4444"></div><span style="color:#ef4444">Construction</span></div>
        <div style="display:flex;align-items:center;gap:5px;margin-bottom:3px"><div style="width:8px;height:8px;border-radius:50%;background:#a16207"></div><span style="color:#a16207">Logging</span></div>
        <div style="display:flex;align-items:center;gap:5px;margin-bottom:3px"><div style="width:8px;height:8px;border-radius:50%;background:#7c3aed"></div><span style="color:#7c3aed">Mining</span></div>
        <div style="display:flex;align-items:center;gap:5px"><div style="width:8px;height:8px;border-radius:50%;background:#22c55e"></div><span style="color:#22c55e">Natural</span></div>
      </div>
    </div>
  </div>
</div>

<script>
'use strict';
const GIBS=(l,d,e='jpg')=>`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${l}/default/${d}/GoogleMapsCompatible/{z}/{y}/{x}.${e}`;
function resolveGIBSLayer(src){
  if(src==='s2')  return{layer:'Sentinel_2_Granule_TrueColor',ext:'png'};
  if(src==='ls9') return{layer:'Landsat_9_OLI_True_Color',ext:'jpg'};
  return{layer:'Landsat_8_OLI_True_Color',ext:'jpg'};
}
const BASE_TILES={osm:'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  terrain:'https://tile.opentopomap.org/{z}/{x}/{y}.png',
  satellite:'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  carto:'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'};
const SAT_LABEL={s2:'Sentinel-2 (ESA/GIBS)',ls8:'Landsat-8 OLI',ls9:'Landsat-9 OLI'};
const NALLA_CENTER=[15.8,79.3],NALLA_BOUNDS=[[14.8,78.4],[16.8,80.2]];
let lastLat=NALLA_CENTER[0],lastLon=NALLA_CENTER[1],satSource='s2',lulcYear=1991;
const LULC_CLASSES=['Vegetation','Crop Land','Scrub Land','Urban Area','Rural Area','Aquaculture','Pond/Lake','Open Land'];
const LULC_COLORS=['#2d8a3e','#d4e157','#8bc34a','#e53935','#ff8f00','#00acc1','#1565c0','#f48fb1'];
const LULC_OPACITY=0.72,GRID_PREC=6;
let digipinGridCells=[],gridLoaded=false;

function changeColor(t1,t2){
  const stable=[{hex:'#1a5c2a',label:'Stable Forest'},{hex:'#2d7a3a',label:'Stable Open Forest'},
    {hex:'#6b7c3a',label:'Stable Scrubland'},{hex:'#d4e157',label:'Stable Agriculture'},
    {hex:'#374151',label:'Stable Barren'},{hex:'#1565c0',label:'Stable Water'},{hex:'#a21caf',label:'Stable Urban'}];
  if(t1===t2) return stable[t1]||{hex:'#374151',label:'No Change'};
  if((t1===0||t1===1)&&t2===3) return{hex:'#dc2626',label:'Forest → Agri'};
  if((t1===0||t1===1)&&t2===6) return{hex:'#7f1d1d',label:'Forest → Urban'};
  if((t1===0||t1===1)&&t2===2) return{hex:'#ea580c',label:'Forest → Scrub'};
  if((t1===0||t1===1)&&t2===4) return{hex:'#c2410c',label:'Forest → Barren'};
  if(t1===0&&t2===1)           return{hex:'#4d7c0f',label:'Dense→Open Forest'};
  if((t2===0||t2===1)&&(t1===2||t1===3||t1===4)) return{hex:'#2563eb',label:'Regrowth'};
  if(t1===2&&t2===3) return{hex:'#f59e0b',label:'Scrub → Agri'};
  if(t1===2&&t2===6) return{hex:'#ef4444',label:'Scrub → Urban'};
  if(t1===3&&t2===6) return{hex:'#f59e0b',label:'Agri → Urban'};
  if(t1===3&&t2===4) return{hex:'#92400e',label:'Agri → Barren'};
  if(t1===6)         return{hex:'#a21caf',label:'Urban Expansion'};
  if(t1===5||t2===5) return{hex:'#0284c7',label:'Water Change'};
  return{hex:'#374151',label:'Minor Change'};
}

function mkMap(id){return L.map(id,{zoomControl:false,attributionControl:false,preferCanvas:true}).setView(NALLA_CENTER,9);}
function baseTile(url){return L.tileLayer(url,{maxZoom:20,tileSize:256});}
function gibsTile(l,d,e='jpg'){return L.tileLayer(GIBS(l,d,e),{maxZoom:13,tileSize:256,errorTileUrl:''});}
function loadBoundary(map,w=1.5){
  fetch('/nallamala_boundary').then(r=>r.json()).then(d=>{
    if(!d.error)L.geoJSON(d,{style:{color:'#00d4aa',weight:w,fillOpacity:0,dashArray:'4 3'}}).addTo(map);
  }).catch(()=>{});
}
function fmt(n,s=''){return n>=1000?(n/1000).toFixed(1)+'k'+s:n+s;}
function sRand(seed){
  let s=seed>>>0;
  return()=>{s+=0x6D2B79F5;let t=Math.imul(s^(s>>>15),1|s);t^=t+Math.imul(t^(t>>>7),61|t);return((t^(t>>>14))>>>0)/4294967296;};
}
function hashStr(str){let h=0;for(let i=0;i<str.length;i++)h=(Math.imul(31,h)+str.charCodeAt(i))|0;return h>>>0;}

function fetchDigipinGrid(cb){
  if(gridLoaded){cb(digipinGridCells);return;}
  fetch('/digipin_grid',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat_min:14.8,lat_max:16.8,lon_min:78.4,lon_max:80.2,precision:GRID_PREC})})
  .then(r=>r.json()).then(d=>{digipinGridCells=d.cells||[];gridLoaded=true;cb(digipinGridCells);})
  .catch(()=>cb([]));
}
function cellLulcClass(dp,yr){
  const rng=sRand(hashStr(dp+String(yr)));const t=(yr-1991)/30;
  const w=[0.45-t*0.25,0.15+t*0.18,0.12-t*0.05,0.05+t*0.12,0.08+t*0.03,0.05,0.05-t*0.02,0.05-t*0.01];
  let cum=0,r=rng();
  for(let i=0;i<w.length;i++){cum+=Math.max(0,w[i]);if(r<cum)return i;}
  return 0;
}

// MAP 1
const m1=mkMap('m1');L.control.zoom({position:'topright'}).addTo(m1);
let m1Base=baseTile(BASE_TILES.osm);m1Base.addTo(m1);
let m1GridLayer=null;
function switchBase(key,evt){
  if(m1Base)m1.removeLayer(m1Base);m1Base=baseTile(BASE_TILES[key]||BASE_TILES.osm);m1Base.addTo(m1);
  if(m1GridLayer)m1GridLayer.bringToFront();
  document.querySelectorAll('#bsw1 .mc-btn').forEach(b=>b.classList.remove('on'));
  if(evt&&evt.target)evt.target.classList.add('on');
}
function drawDigipinGridM1(cells){
  if(m1GridLayer)m1.removeLayer(m1GridLayer);
  const layers=[];
  cells.forEach(c=>{
    const rect=L.rectangle([[c.lat_min,c.lon_min],[c.lat_max,c.lon_max]],
      {color:'#00d4aa',weight:.7,fillColor:'transparent',fillOpacity:0,dashArray:'2 4',interactive:true});
    rect.bindTooltip(`<b style="color:#00d4aa;letter-spacing:2px">${c.digipin}</b><br>
      <span style="color:#4a6d8a;font-size:9px">${c.center_lat.toFixed(4)}°N ${c.center_lon.toFixed(4)}°E</span>`,
      {sticky:true,direction:'top'});
    rect.on('click',e=>{L.DomEvent.stopPropagation(e);handleClick(c.center_lat,c.center_lon);});
    layers.push(rect);
  });
  m1GridLayer=L.layerGroup(layers).addTo(m1);
}
fetch('/nallamala_boundary').then(r=>r.json()).then(d=>{
  if(d.error){m1.fitBounds(NALLA_BOUNDS,{padding:[20,20]});return;}
  const lyr=L.geoJSON(d,{style:{color:'#00d4aa',weight:2.5,fillColor:'#00d4aa',fillOpacity:.05,dashArray:'4 3'}}).addTo(m1);
  m1.fitBounds(lyr.getBounds(),{padding:[20,20]});
}).catch(()=>m1.fitBounds(NALLA_BOUNDS,{padding:[20,20]}));
fetch('/india_boundary').then(r=>r.json()).then(d=>{
  if(!d.error)L.geoJSON(d,{style:{color:'#3b82f6',weight:.6,fillOpacity:0}}).addTo(m1);
}).catch(()=>{});
fetchDigipinGrid(cells=>{
  drawDigipinGridM1(cells);
  document.getElementById('grid-tag-1').textContent=`PREC-${GRID_PREC} · ${cells.length} CELLS`;
});
let hoverMark=null,hoverT=null;
m1.on('mousemove',e=>{
  clearTimeout(hoverT);
  hoverT=setTimeout(()=>{
    fetch('/encode',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({lat:e.latlng.lat,lon:e.latlng.lng,precision:10})})
    .then(r=>r.json()).then(d=>{
      if(d.error)return;
      if(hoverMark)m1.removeLayer(hoverMark);
      hoverMark=L.marker([e.latlng.lat,e.latlng.lng],{icon:L.divIcon({
        className:'',iconAnchor:[48,20],
        html:`<div style="background:rgba(11,15,20,.97);color:#00d4aa;padding:2px 8px;border-radius:2px;font-family:monospace;font-size:9px;border:1px solid #00d4aa;letter-spacing:3px;white-space:nowrap">${d.digipin}</div>`
      })}).addTo(m1);
    }).catch(()=>{});
  },55);
});
m1.on('mouseout',()=>{if(hoverMark){m1.removeLayer(hoverMark);hoverMark=null;}});
let pin1=null,rect1=null;
m1.on('click',e=>handleClick(e.latlng.lat,e.latlng.lng));

// MAP 2
const m2=mkMap('m2');L.control.zoom({position:'topright'}).addTo(m2);
baseTile(BASE_TILES.osm).addTo(m2);m2.setView(NALLA_CENTER,9);loadBoundary(m2,1.5);
let m2LulcLayer=null,m2SelRect=null;
function setLulcYear(yr,btn){
  lulcYear=yr;
  document.querySelectorAll('.lulc-year-btn').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active');redrawLulcGrid();
}
function redrawLulcGrid(){
  if(m2LulcLayer)m2.removeLayer(m2LulcLayer);
  if(!digipinGridCells.length)return;
  const layers=[];
  digipinGridCells.forEach(c=>{
    const cls=cellLulcClass(c.digipin,lulcYear),color=LULC_COLORS[cls];
    const rect=L.rectangle([[c.lat_min,c.lon_min],[c.lat_max,c.lon_max]],
      {color:'rgba(0,0,0,0.2)',weight:.5,fillColor:color,fillOpacity:LULC_OPACITY,interactive:true});
    rect.bindTooltip(`<span style="color:${color};font-weight:700">${LULC_CLASSES[cls]}</span><br>
      <span style="color:#00d4aa;font-size:9px;letter-spacing:1px">${c.digipin}</span><br>
      <span style="color:#4a6d8a;font-size:9px">Click for time variation</span>`,{sticky:true,direction:'top'});
    rect.on('click',e=>{L.DomEvent.stopPropagation(e);showLulcPopup(c,e.containerPoint);});
    layers.push(rect);
  });
  m2LulcLayer=L.layerGroup(layers).addTo(m2);
}
function showLulcPopup(cell,pt){
  const popup=document.getElementById('lulc-popup');
  document.getElementById('lp-dp').textContent=`${cell.digipin}  ·  ${cell.center_lat.toFixed(4)}°N ${cell.center_lon.toFixed(4)}°E`;
  if(m2SelRect)m2.removeLayer(m2SelRect);
  m2SelRect=L.rectangle([[cell.lat_min,cell.lon_min],[cell.lat_max,cell.lon_max]],
    {color:'#ffffff',weight:2,fillOpacity:0}).addTo(m2);
  fetch('/lulc_timeseries',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat:cell.center_lat,lon:cell.center_lon})})
  .then(r=>r.json()).then(d=>{
    drawLulcBarChart(d);
    const pr=document.getElementById('m2').parentElement.getBoundingClientRect();
    const mr=document.getElementById('m2').getBoundingClientRect();
    let px=(pt.x+mr.left-pr.left)+10,py=(pt.y+mr.top-pr.top)-80;
    px=Math.max(5,Math.min(px,pr.width-235));py=Math.max(5,Math.min(py,pr.height-180));
    popup.style.left=px+'px';popup.style.top=py+'px';popup.style.display='block';
  }).catch(()=>{});
}
function drawLulcBarChart(d){
  const cv=document.getElementById('lulc-chart'),ctx=cv.getContext('2d');
  const W=210,H=130,P={l:8,r:8,t:18,b:20};
  ctx.clearRect(0,0,W,H);
  const bw=(W-P.l-P.r)/d.years.length-4,hS=(H-P.t-P.b)/100;
  ctx.fillStyle='#4a6d8a';ctx.font='7px JetBrains Mono,monospace';ctx.textAlign='center';
  d.years.forEach((yr,xi)=>{ctx.fillText(yr,P.l+xi*(bw+4)+bw/2,H-P.b+10);});
  d.years.forEach((yr,xi)=>{
    let cum=0;const bx=P.l+xi*(bw+4);
    d.data[yr].forEach((v,ci)=>{
      const bh=v*hS,by=H-P.b-(cum+v)*hS;
      ctx.fillStyle=LULC_COLORS[ci];ctx.fillRect(bx,by,bw,bh);cum+=v;
    });
    if(yr===lulcYear){ctx.strokeStyle='#ffffff';ctx.lineWidth=1.5;ctx.strokeRect(bx,P.t,bw,H-P.t-P.b);}
  });
  const av=d.data[lulcYear],di=av.indexOf(Math.max(...av));
  ctx.fillStyle='#00d4aa';ctx.font='6px JetBrains Mono,monospace';ctx.textAlign='left';
  ctx.fillText(`${LULC_CLASSES[di]} ${av[di].toFixed(1)}%`,P.l,P.t-5);
}
m2.on('click',()=>{document.getElementById('lulc-popup').style.display='none';if(m2SelRect){m2.removeLayer(m2SelRect);m2SelRect=null;}});
fetchDigipinGrid(()=>redrawLulcGrid());

// MAP 3
const m3=mkMap('m3');L.control.zoom({position:'topright'}).addTo(m3);
baseTile(BASE_TILES.satellite).addTo(m3);m3.setView(NALLA_CENTER,9);loadBoundary(m3);
let m3Sat=null,cellRect3=null,cellMark3=null;
function buildCellSat(d){
  const {layer,ext}=resolveGIBSLayer(satSource);
  if(m3Sat)m3.removeLayer(m3Sat);
  m3Sat=L.tileLayer(GIBS(layer,document.getElementById('sat3-date').value,ext),{maxZoom:13,tileSize:256,opacity:.75,errorTileUrl:''});
  m3Sat.addTo(m3);
  if(d){
    m3.setView([d.center_lat,d.center_lon],16);
    if(cellRect3)m3.removeLayer(cellRect3);if(cellMark3)m3.removeLayer(cellMark3);
    cellRect3=L.rectangle([[d.lat_min,d.lon_min],[d.lat_max,d.lon_max]],{color:'#00d4aa',weight:3,fillColor:'#00d4aa',fillOpacity:.18}).addTo(m3);
    cellMark3=L.circleMarker([d.center_lat,d.center_lon],{radius:3,color:'#ef4444',fillColor:'#ef4444',fillOpacity:1,weight:2}).addTo(m3);
    drawCellCanvas(d);
  }
}
buildCellSat();
function drawCellCanvas(d){
  const cv=document.getElementById('cell-canvas'),ctx=cv.getContext('2d');
  const W=80,H=80,SC=14,cx=d.cell_lon_m,cy=d.cell_lat_m,ox=(W-cx*SC)/2,oy=(H-cy*SC)/2;
  ctx.clearRect(0,0,W,H);ctx.strokeStyle='#1a2f45';ctx.lineWidth=.5;
  for(let x=0;x<W;x+=SC){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
  for(let y=0;y<H;y+=SC){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
  ctx.fillStyle='rgba(0,212,170,.15)';ctx.fillRect(ox,oy,cx*SC,cy*SC);
  ctx.strokeStyle='#00d4aa';ctx.lineWidth=2;ctx.strokeRect(ox,oy,cx*SC,cy*SC);
  ctx.fillStyle='#00d4aa';ctx.font='6.5px JetBrains Mono,monospace';ctx.fillText(`${cx.toFixed(2)}m`,ox+2,oy-2);
  document.getElementById('cell-dims').textContent=`${cy.toFixed(2)}m × ${cx.toFixed(2)}m`;
  document.getElementById('cell-area').textContent=`${d.area_m2.toFixed(1)} m²  ·  PREC-10`;
}

// SANKEY
const SK_CLS=['Dense Forest','Open Forest','Scrubland','Agriculture','Barren'];
const SK_COL=['#16a34a','#22c55e','#ca8a04','#f97316','#ef4444'];
function fetchSankey(lat,lon,from,to){
  document.getElementById('sk-init').style.display='flex';
  document.getElementById('sk-init').textContent='LOADING ANALYSIS…';
  document.getElementById('metric-strip').style.display='none';
  document.getElementById('sk-source').style.display='none';
  fetch('/lulc_matrix',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat,lon,from_date:from,to_date:to})})
  .then(r=>r.json()).then(d=>{
    document.getElementById('sk-init').style.display='none';
    drawSankey(d.matrix,from,to,'sk-svg','sk-body','sk-tip');
    const dr=d.matrix[0],st=dr[0],ls=dr.reduce((a,b)=>a+b,0)-st;
    const ai=d.matrix.reduce((s,r,i)=>i===0?s:s+r[3],0),rg=d.matrix[1][0]+d.matrix[2][0];
    document.getElementById('m-defor').textContent=fmt(ls,' ha');
    document.getElementById('m-stable').textContent=fmt(st,' ha');
    document.getElementById('m-encr').textContent=fmt(ai,' ha');
    document.getElementById('m-regrow').textContent=fmt(rg,' ha');
    document.getElementById('metric-strip').style.display='flex';
    document.getElementById('sk-source').style.display='block';
    document.getElementById('sk-source').textContent=`SOURCE · ${SAT_LABEL[satSource]||satSource} · LULC spectral classification · ${from} → ${to}`;
    document.getElementById('t4').textContent=`${from} → ${to}  ·  ${SAT_LABEL[satSource]||satSource}`;
  }).catch(()=>{document.getElementById('sk-init').textContent='ERROR — RETRY';document.getElementById('sk-init').style.display='flex';});
}
function drawSankey(T,from,to,svgId,bodyId,tipId){
  const svg=d3.select('#'+svgId);svg.selectAll('*').remove();
  const body=document.getElementById(bodyId),W=body.clientWidth||400,H=body.clientHeight||200;
  svg.attr('width',W).attr('height',H);
  const n=5,P={t:12,b:18,l:85,r:85},BW=8,GAP=4,IH=H-P.t-P.b,SH=(IH-GAP*(n-1))/n;
  const sT=T.map(r=>r.reduce((a,b)=>a+b,0)),dT=T[0].map((_,j)=>T.reduce((s,r)=>s+r[j],0));
  const mT=Math.max(...sT,...dT);
  function bg(i,tots){const sy=P.t+i*(SH+GAP),bh=Math.max(4,SH*(tots[i]/mT));return{y:sy+(SH-bh)/2,h:bh,mid:sy+SH/2};}
  const sO=T.map((_,i)=>({...bg(i,sT),cur:0})),dO=T[0].map((_,j)=>({...bg(j,dT),cur:0}));
  const xL=P.l+BW,xR=W-P.r-BW,mv=Math.max(...T.flat());
  const tip=document.getElementById(tipId),br=document.getElementById(bodyId).getBoundingClientRect();
  T.forEach((row,i)=>row.forEach((v,j)=>{
    if(v<10)return;
    const sh=sO[i].h*(v/sT[i]),dh=dO[j].h*(v/dT[j]),y0=sO[i].y+sO[i].cur,y1=dO[j].y+dO[j].cur;
    sO[i].cur+=sh;dO[j].cur+=dh;
    const mx=(xL+xR)/2,op=i===j?0.08+v/mv*0.1:0.15+v/mv*0.5;
    svg.append('path')
      .attr('d',[`M ${xL} ${y0}`,`C ${mx} ${y0},${mx} ${y1},${xR} ${y1}`,`L ${xR} ${y1+dh}`,`C ${mx} ${y1+dh},${mx} ${y0+sh},${xL} ${y0+sh} Z`].join(' '))
      .attr('fill',SK_COL[i]).attr('opacity',op).attr('cursor','pointer')
      .on('mouseover',function(){d3.select(this).attr('opacity',Math.min(op+.28,.9));
        tip.innerHTML=`<span style="color:${SK_COL[i]}">${SK_CLS[i]}</span> → <span style="color:${SK_COL[j]}">${SK_CLS[j]}</span><br>${fmt(v,' ha')}`;
        tip.style.display='block';})
      .on('mousemove',ev=>{tip.style.left=(ev.clientX-br.left+9)+'px';tip.style.top=(ev.clientY-br.top-36)+'px';})
      .on('mouseout',function(){d3.select(this).attr('opacity',op);tip.style.display='none';});
  }));
  for(let i=0;i<n;i++){
    const{y:sy,h:sh,mid:sm}=bg(i,sT),{y:dy,h:dh,mid:dm}=bg(i,dT);
    svg.append('rect').attr('x',P.l).attr('y',sy).attr('width',BW).attr('height',sh).attr('fill',SK_COL[i]).attr('rx',1);
    svg.append('text').attr('x',P.l-4).attr('y',sm).attr('text-anchor','end').attr('dominant-baseline','middle').attr('fill',SK_COL[i]).attr('font-size',8).attr('font-family','JetBrains Mono,monospace').text(SK_CLS[i]);
    svg.append('text').attr('x',xL+3).attr('y',sy+sh/2).attr('dominant-baseline','middle').attr('fill','#243d56').attr('font-size',6.5).attr('font-family','monospace').text(fmt(sT[i],' ha'));
    svg.append('rect').attr('x',xR).attr('y',dy).attr('width',BW).attr('height',dh).attr('fill',SK_COL[i]).attr('rx',1);
    svg.append('text').attr('x',W-P.r+4).attr('y',dm).attr('text-anchor','start').attr('dominant-baseline','middle').attr('fill',SK_COL[i]).attr('font-size',8).attr('font-family','JetBrains Mono,monospace').text(SK_CLS[i]);
    svg.append('text').attr('x',xR-3).attr('y',dy+dh/2).attr('text-anchor','end').attr('dominant-baseline','middle').attr('fill','#243d56').attr('font-size',6.5).attr('font-family','monospace').text(fmt(dT[i],' ha'));
  }
  svg.append('text').attr('x',P.l).attr('y',H-3).attr('font-size',6.5).attr('fill','#2a3d55').attr('font-family','monospace').text(from);
  svg.append('text').attr('x',W-P.r).attr('y',H-3).attr('text-anchor','end').attr('font-size',6.5).attr('fill','#2a3d55').attr('font-family','monospace').text(to);
  const nd=dT[0]-sT[0],nc=nd>=0?'#22c55e':'#ef4444';
  svg.append('text').attr('x',W/2).attr('y',H-3).attr('text-anchor','middle').attr('font-size',6.5).attr('fill',nc).attr('font-family','monospace').text(`Dense Forest net: ${nd>=0?'+':''}${fmt(nd,' ha')}`);
}

// MAP 5 — CHANGE DETECTION
const m5=mkMap('m5');L.control.zoom({position:'topright'}).addTo(m5);
baseTile(BASE_TILES.carto).addTo(m5);m5.setView(NALLA_CENTER,9);loadBoundary(m5,2);
let m5Sat=null,cdCells=[],cdFromYear=2001,cdToYear=2021;
const cdCanvas=document.getElementById('cd-canvas'),cdCtx=cdCanvas.getContext('2d');
const N_PIXELS=16;

function getPixelClass(dp,row,col,yr){
  const rng=sRand(hashStr(`${dp}${row}${col}${yr}`));
  const h=hashStr(dp),vb=0.2+(h%100)/100*0.6;
  const e=Math.min(row,N_PIXELS-1-row,col,N_PIXELS-1-col)/(N_PIXELS/2);
  const vp=Math.min(0.95,vb*(0.5+e*0.5)),t=(yr-1991)/30;
  const w=[vp*(0.55-t*0.20),vp*(0.25-t*0.05),vp*(0.10-t*0.03),
           (1-vp)*(0.45+t*0.20),(1-vp)*(0.20-t*0.05),0.04,(1-vp)*(0.05+t*0.12)].map(x=>Math.max(0,x));
  const tot=w.reduce((a,b)=>a+b,0);let cum=0,r=rng();
  for(let i=0;i<w.length;i++){cum+=w[i]/tot;if(r<cum)return i;}
  return 3;
}
function buildCdPixelData(cells,fy,ty){
  cdCells=cells.map(c=>{
    const pixels=[];
    for(let r=0;r<N_PIXELS;r++){const pr=[];for(let cc=0;cc<N_PIXELS;cc++){const t1=getPixelClass(c.digipin,r,cc,fy),t2=getPixelClass(c.digipin,r,cc,ty);pr.push({t1,t2,color:changeColor(t1,t2).hex});}pixels.push(pr);}
    return{...c,pixels};
  });
}
function renderCdCanvas(){
  if(!cdCells.length)return;
  const el=document.getElementById('m5'),W=el.clientWidth,H=el.clientHeight;
  cdCanvas.width=W;cdCanvas.height=H;cdCanvas.style.width=W+'px';cdCanvas.style.height=H+'px';
  cdCtx.clearRect(0,0,W,H);
  cdCells.forEach(c=>{
    const sw=m5.latLngToContainerPoint([c.lat_min,c.lon_min]),ne=m5.latLngToContainerPoint([c.lat_max,c.lon_max]);
    const x0=Math.round(sw.x),y0=Math.round(ne.y),cW=Math.round(ne.x-sw.x),cH=Math.round(sw.y-ne.y);
    if(cW<1||cH<1||x0>W||y0>H||x0+cW<0||y0+cH<0)return;
    c.pixels.forEach((pr,ri)=>pr.forEach((px,ci)=>{
      cdCtx.fillStyle=px.color;
      cdCtx.fillRect(Math.round(x0+ci*cW/N_PIXELS),Math.round(y0+ri*cH/N_PIXELS),Math.ceil(cW/N_PIXELS)+1,Math.ceil(cH/N_PIXELS)+1);
    }));
    if(cW>10){cdCtx.strokeStyle='rgba(0,0,0,0.25)';cdCtx.lineWidth=.5;cdCtx.strokeRect(x0,y0,cW,cH);}
  });
}
function computeCdStats(){
  if(!cdCells.length)return;
  let total=0,sf=0,fl=0,fg=0,ue=0;const tc={};
  cdCells.forEach(c=>c.pixels.forEach(pr=>pr.forEach(px=>{
    total++;const{t1,t2}=px;
    if((t1===0||t1===1)&&(t2===0||t2===1))sf++;
    if((t1===0||t1===1)&&t2>1)fl++;
    if(t2<2&&t1>1)fg++;
    if(t2===6&&t1!==6)ue++;
    const k=changeColor(t1,t2).label;tc[k]=(tc[k]||0)+1;
  })));
  const p=v=>(v/total*100).toFixed(1)+'%';
  document.getElementById('cds-stable').textContent=p(sf);
  document.getElementById('cds-loss').textContent=p(fl);
  document.getElementById('cds-gain').textContent=p(fg);
  document.getElementById('cds-urban').textContent=p(ue);
  const dom=Object.entries(tc).sort((a,b)=>b[1]-a[1]).find(([k])=>!k.startsWith('Stable'))||Object.entries(tc)[0];
  document.getElementById('cds-dom').textContent=dom?dom[0]:'—';
}
function updateChangeDetection(from,to){
  const fy=parseInt(from),ty=parseInt(to);
  cdFromYear=fy;cdToYear=ty;
  document.getElementById('cd-period').textContent=`${fy} → ${ty}  ·  CLASS TRANSITION MAP`;
  document.getElementById('cd-loading').style.display='flex';
  if(m5Sat)m5.removeLayer(m5Sat);
  const{layer,ext}=resolveGIBSLayer(satSource);
  m5Sat=L.tileLayer(GIBS(layer,to,ext),{maxZoom:13,tileSize:256,opacity:.18,errorTileUrl:''});m5Sat.addTo(m5);
  fetchDigipinGrid(cells=>{
    setTimeout(()=>{
      buildCdPixelData(cells,fy,ty);renderCdCanvas();computeCdStats();
      document.getElementById('cd-loading').style.display='none';
      document.getElementById('t5').textContent=`${fy} → ${ty}  ·  ${cells.length} DIGIPIN cells  ·  ${N_PIXELS}×${N_PIXELS} px/cell`;
    },50);
  });
}
m5.on('moveend zoomend resize',()=>{if(cdCells.length)renderCdCanvas();});
m5.on('click',e=>handleClick(e.latlng.lat,e.latlng.lng));
fetchDigipinGrid(()=>updateChangeDetection(document.getElementById('d0').value,document.getElementById('d1').value));

// MAP 6 — ENCROACHMENT
const m6=mkMap('m6');L.control.zoom({position:'topright'}).addTo(m6);
baseTile(BASE_TILES.osm).addTo(m6);loadBoundary(m6,1.8);
let m6Sat=null,encGroup=null;
const SEV_COLORS={ACTIVE:'#ef4444',WARNING:'#f97316',WATCH:'#eab308'};
function loadEncroachmentAlerts(){
  const from=document.getElementById('d0').value,to=document.getElementById('d1').value;
  const fy=parseInt(from),ty=parseInt(to);
  if(m6Sat)m6.removeLayer(m6Sat);
  const{layer,ext}=resolveGIBSLayer(satSource);
  m6Sat=L.tileLayer(GIBS(layer,to,ext),{maxZoom:13,tileSize:256,opacity:.45,errorTileUrl:''});m6Sat.addTo(m6);
  document.getElementById('t6').textContent='Scanning…';
  fetch('/alert_scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from_year:fy,to_year:ty})})
  .then(r=>r.json()).then(d=>{
    renderEncAlerts(d);
    document.getElementById('t6').textContent=`${fy}→${ty} · ${d.count} alerts · ${d.total_ha.toLocaleString()} ha`;
  }).catch(()=>{document.getElementById('t6').textContent='Alert scan failed';});
}
function renderEncAlerts(data){
  if(encGroup)m6.removeLayer(encGroup);
  const layers=[],SZ={ACTIVE:3,WARNING:2,WATCH:1};
  [...data.alerts].sort((a,b)=>SZ[a.severity]-SZ[b.severity]).forEach(a=>{
    const R=5+Math.sqrt(a.area_ha)*0.18,sc=SEV_COLORS[a.severity],op=a.severity==='ACTIVE'?0.72:a.severity==='WARNING'?0.52:0.35;
    layers.push(L.circleMarker([a.lat,a.lon],{radius:R*2.2,color:sc,fillColor:sc,fillOpacity:.04,weight:a.severity==='ACTIVE'?1.2:.7,dashArray:a.severity==='ACTIVE'?'3 2':'4 4'}));
    const cb=Math.round(a.confidence*100);
    L.circleMarker([a.lat,a.lon],{radius:R,color:a.color,fillColor:a.color,fillOpacity:op,weight:1.5})
      .bindPopup(`<div style="font-family:'JetBrains Mono',monospace;min-width:230px;line-height:1">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px">
          <span style="color:${a.color};font-weight:700;font-size:11px">${a.type.replace('_',' ')}</span>
          <span style="background:${sc};color:#000;font-size:9px;font-weight:700;padding:1px 6px;border-radius:2px">${a.severity}</span>
        </div>
        <div style="width:100%;height:3px;background:rgba(255,255,255,.08);border-radius:2px;margin-bottom:7px">
          <div style="width:${cb}%;height:100%;background:${a.color};border-radius:2px"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:3px 10px;margin-bottom:7px">
          <span style="color:#4a6d8a;font-size:9px">Alert ID</span><span style="color:#c8daea;font-size:9px">${a.alert_id}</span>
          <span style="color:#4a6d8a;font-size:9px">DIGIPIN</span><span style="color:#00d4aa;font-size:9px">${a.digipin}</span>
          <span style="color:#4a6d8a;font-size:9px">Detected</span><span style="color:#c8daea;font-size:9px">${a.detected_date}</span>
          <span style="color:#4a6d8a;font-size:9px">Area</span><span style="color:${a.color};font-weight:700;font-size:9px">${a.area_ha} ha</span>
          <span style="color:#4a6d8a;font-size:9px">Confidence</span><span style="color:${a.color};font-weight:700;font-size:9px">${a.confidence_pct}</span>
          <span style="color:#4a6d8a;font-size:9px">Velocity</span><span style="color:#f97316;font-size:9px">${a.velocity_ha_yr} ha/yr</span>
        </div>
        <div style="border-top:1px solid #1a2f45;padding-top:6px;margin-bottom:6px">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:2px 10px">
            <span style="color:#8aadca;font-size:9px">NDVI Before</span><span style="color:#22c55e;font-size:9px">${a.evidence.ndvi_before}</span>
            <span style="color:#8aadca;font-size:9px">NDVI After</span><span style="color:#ef4444;font-size:9px">${a.evidence.ndvi_after}</span>
            <span style="color:#8aadca;font-size:9px">NDVI Drop</span><span style="color:#f97316;font-weight:700;font-size:9px">${a.evidence.ndvi_drop}</span>
            <span style="color:#8aadca;font-size:9px">Bare Soil</span><span style="color:#eab308;font-size:9px">${a.evidence.bare_soil}</span>
          </div>
        </div>
        <div style="border-top:1px solid #1a2f45;padding-top:5px;color:#fbbf24;font-size:9px;line-height:1.6">${a.action}</div>
      </div>`,{maxWidth:260}).addTo(m6);
    layers.push(L.circleMarker([a.lat,a.lon],{radius:R,color:a.color,fillColor:a.color,fillOpacity:op,weight:1.5}));
  });
  encGroup=L.layerGroup(layers).addTo(m6);
  m6.fitBounds([[14.7,78.3],[16.9,80.3]],{padding:[16,16]});
  const c=data.counts;
  document.getElementById('enc-active').textContent=c.ACTIVE||0;
  document.getElementById('enc-warning').textContent=c.WARNING||0;
  document.getElementById('enc-watch').textContent=c.WATCH||0;
  document.getElementById('enc-total-ha').textContent=data.total_ha.toLocaleString()+' ha';
  document.getElementById('enc-dominant').textContent=(data.dominant||'—').replace('_',' ');
  document.getElementById('enc-total-count').textContent=data.count;
  document.getElementById('enc-counts').style.display='block';
  document.getElementById('enc-summary').style.display='block';
}

// MAIN CLICK
function handleClick(lat,lon){
  lastLat=lat;lastLon=lon;
  fetch('/encode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat,lon,precision:10})})
  .then(r=>r.json()).then(enc=>{
    if(enc.error)return;
    fetch('/decode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({digipin:enc.digipin})})
    .then(r=>r.json()).then(d=>{
      if(d.error)return;
      const dp=enc.digipin,badge=document.getElementById('dp-badge');
      badge.textContent=dp;badge.style.display='block';
      if(pin1)m1.removeLayer(pin1);if(rect1)m1.removeLayer(rect1);
      pin1=L.circleMarker([lat,lon],{radius:5,color:'#00d4aa',fillColor:'#00d4aa',fillOpacity:1,weight:2}).addTo(m1);
      rect1=L.rectangle([[d.lat_min,d.lon_min],[d.lat_max,d.lon_max]],{color:'#fff',weight:2.5,fillColor:'#00d4aa',fillOpacity:.2}).addTo(m1);
      ['ci-dp','ci-lat','ci-lon','ci-cell','ci-area'].forEach((id,i)=>{
        document.getElementById(id).textContent=[dp,d.center_lat.toFixed(6)+'°',d.center_lon.toFixed(6)+'°',
          `${d.cell_lat_m.toFixed(2)}m × ${d.cell_lon_m.toFixed(2)}m`,`${d.area_m2.toFixed(1)} m²`][i];
      });
      document.getElementById('cinfo').style.display='block';
      document.getElementById('loc-chip').textContent=`${d.center_lat.toFixed(4)}°N · ${d.center_lon.toFixed(4)}°E`;
      document.getElementById('t1').textContent=dp;
      document.getElementById('t2').textContent=`${dp} · Click cells for class variation`;
      const z=Math.min(15,m1.getZoom()+2);
      [m2,m3,m5,m6].forEach(m=>m.setView([d.center_lat,d.center_lon],z));
      buildCellSat(d);
      const from=document.getElementById('d0').value,to=document.getElementById('d1').value;
      fetchSankey(lat,lon,from,to);loadEncroachmentAlerts();
      setTimeout(()=>renderCdCanvas(),300);
    });
  });
}

function onSatSourceChange(){
  satSource=document.getElementById('satSource').value;
  buildCellSat();
  updateChangeDetection(document.getElementById('d0').value,document.getElementById('d1').value);
  loadEncroachmentAlerts();
}
function doSearch(){
  const q=document.getElementById('searchInput').value.trim();if(!q)return;
  const dp=q.replace(/-/g,'').toUpperCase();
  if(/^[23456789CFJKLMPT]{3,10}$/.test(dp)){
    fetch('/decode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({digipin:dp})})
    .then(r=>r.json()).then(d=>{
      if(d.error){showErr('Invalid DIGIPIN');return;}
      [m1,m2,m3,m5,m6].forEach(m=>m.setView([d.center_lat,d.center_lon],14));
      handleClick(d.center_lat,d.center_lon);
    }).catch(()=>showErr('Server error'));
    return;
  }
  fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=1&countrycodes=in`,{headers:{'Accept-Language':'en'}})
  .then(r=>r.json()).then(res=>{
    if(!res.length){showErr('Place not found');return;}
    const lat=parseFloat(res[0].lat),lon=parseFloat(res[0].lon);
    [m1,m2,m3,m5,m6].forEach(m=>m.setView([lat,lon],13));handleClick(lat,lon);
  }).catch(()=>showErr('Network error'));
}
function showErr(msg){const el=document.getElementById('search-err');el.textContent=msg;el.style.display='block';setTimeout(()=>el.style.display='none',3000);}
document.getElementById('searchInput').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();doSearch();}});
function doAnalyse(){
  const from=document.getElementById('d0').value,to=document.getElementById('d1').value;
  if(!from||!to){showErr('Set both dates');return;}
  document.getElementById('sat3-date').value=from;buildCellSat();
  updateChangeDetection(from,to);fetchSankey(lastLat,lastLon,from,to);loadEncroachmentAlerts();
}
let rt;window.addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(()=>{renderCdCanvas();fetchSankey(lastLat,lastLon,document.getElementById('d0').value,document.getElementById('d1').value);},180);});
</script>

<!-- FULL VIEW MODAL -->
<div id="fv-overlay">
  <div id="fv-topbar">
    <span id="fv-num">01</span><span id="fv-title">PANEL</span><span id="fv-tag">—</span>
    <div id="fv-tools">
      <div id="fv-base-sw" style="display:none">
        <button class="fv-mc-btn on" onclick="fvSwitchBase('osm',this)">OSM</button>
        <button class="fv-mc-btn" onclick="fvSwitchBase('terrain',this)">TERRAIN</button>
        <button class="fv-mc-btn" onclick="fvSwitchBase('satellite',this)">SATELLITE</button>
        <button class="fv-mc-btn" onclick="fvSwitchBase('carto',this)">CARTO</button>
      </div>
      <div id="fv-lulc-years" style="display:none;gap:4px;align-items:center">
        <span style="font-size:.52rem;color:var(--muted);letter-spacing:1px">YEAR</span>
        <button class="fv-mc-btn on" onclick="fvSetLulcYear(1991,this)">1991</button>
        <button class="fv-mc-btn" onclick="fvSetLulcYear(2001,this)">2001</button>
        <button class="fv-mc-btn" onclick="fvSetLulcYear(2011,this)">2011</button>
        <button class="fv-mc-btn" onclick="fvSetLulcYear(2021,this)">2021</button>
      </div>
      <div id="fv-cd-period" style="display:none;font-size:.55rem;color:var(--accent2);letter-spacing:1px"></div>
      <button id="fv-close" onclick="closeFullView()">✕ CLOSE</button>
    </div>
  </div>
  <div id="fv-body">
    <div id="fv-map-wrap" style="display:none"></div>
    <div id="fv-graph-wrap" style="display:none">
      <div id="fv-graph-header">
        <div id="fv-metrics" style="display:flex;gap:0;flex:1">
          <div class="metric"><div class="metric-val danger" id="fv-m-defor">—</div><div class="metric-lbl">FOREST LOSS (ha)</div></div>
          <div class="metric"><div class="metric-val" id="fv-m-stable">—</div><div class="metric-lbl">STABLE FOREST (ha)</div></div>
          <div class="metric"><div class="metric-val warn" id="fv-m-encr">—</div><div class="metric-lbl">AGRI ENCROACH (ha)</div></div>
          <div class="metric"><div class="metric-val" id="fv-m-regrow">—</div><div class="metric-lbl">REGROWTH (ha)</div></div>
        </div>
      </div>
      <div id="fv-graph-body"><svg id="fv-sk-svg" style="display:block"></svg><div class="sk-tip" id="fv-sk-tip"></div></div>
      <div class="source-label" id="fv-sk-source"></div>
    </div>
    <div id="fv-overlays"></div>
    <canvas id="fv-cd-canvas"></canvas>
  </div>
</div>

<script>
'use strict';
let fvMap=null,fvMapBase=null,fvCurrentPanel=0,fvLulcLayer=null,fvLulcYearActive=lulcYear;
const FV_META={1:{num:'01',title:'DIGIPIN Reference Map',tag:'DIGIPIN Grid Overlay · Nallamala Reserve'},
  2:{num:'02',title:'LULC Temporal Viewer',tag:'1991–2021 · Click cell for variation'},
  3:{num:'03',title:'Cell-Scale Satellite View',tag:'High-resolution GIBS imagery'},
  4:{num:'04',title:'Land Cover Transition · Sankey',tag:'Transition flow analysis'},
  5:{num:'05',title:'Change Detection Map',tag:'Raster-style T1→T2 pixel transitions'},
  6:{num:'06',title:'Encroachment Alert Map',tag:'AI-classified · spectral + spatial evidence'}};

function openFullView(n){
  fvCurrentPanel=n;const m=FV_META[n];
  document.getElementById('fv-num').textContent=m.num;
  document.getElementById('fv-title').textContent=m.title;
  document.getElementById('fv-tag').textContent=m.tag;
  ['fv-base-sw','fv-lulc-years','fv-cd-period','fv-map-wrap','fv-graph-wrap'].forEach(id=>{
    document.getElementById(id).style.display='none';
  });
  document.getElementById('fv-overlays').innerHTML='';
  document.getElementById('fv-cd-canvas').style.display='none';
  document.getElementById('fv-overlay').classList.add('active');
  n===4?_fvOpenSankey():_fvOpenMap(n);
}
function _fvOpenSankey(){
  document.getElementById('fv-graph-wrap').style.display='flex';
  ['defor','stable','encr','regrow'].forEach(k=>{
    const s=document.getElementById('m-'+k);
    if(s)document.getElementById('fv-m-'+k).textContent=s.textContent;
  });
  document.getElementById('fv-sk-source').textContent=document.getElementById('sk-source')?.textContent||'';
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    const from=document.getElementById('d0').value,to=document.getElementById('d1').value;
    fetch('/lulc_matrix',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({lat:lastLat,lon:lastLon,from_date:from,to_date:to})})
    .then(r=>r.json()).then(d=>{
      drawSankey(d.matrix,from,to,'fv-sk-svg','fv-graph-body','fv-sk-tip');
      const dr=d.matrix[0],st=dr[0],ls=dr.reduce((a,b)=>a+b,0)-st;
      document.getElementById('fv-m-defor').textContent=fmt(ls,' ha');
      document.getElementById('fv-m-stable').textContent=fmt(st,' ha');
      document.getElementById('fv-m-encr').textContent=fmt(d.matrix.reduce((s,r,i)=>i===0?s:s+r[3],0),' ha');
      document.getElementById('fv-m-regrow').textContent=fmt(d.matrix[1][0]+d.matrix[2][0],' ha');
    }).catch(()=>{});
  }));
}
function _fvOpenMap(n){
  document.getElementById('fv-map-wrap').style.display='block';
  const srcMap=[null,m1,m2,m3,null,m5,m6][n];
  const center=srcMap?srcMap.getCenter():L.latLng(NALLA_CENTER),zoom=srcMap?srcMap.getZoom():9;
  if(fvMap){fvMap.remove();fvMap=null;fvMapBase=null;fvLulcLayer=null;}
  fvMap=L.map('fv-map-wrap',{zoomControl:true,attributionControl:false,preferCanvas:true}).setView(center,zoom);
  L.control.zoom({position:'topright'}).addTo(fvMap);
  const bk=n===3?'satellite':n===5?'carto':'osm';
  fvMapBase=baseTile(BASE_TILES[bk]);fvMapBase.addTo(fvMap);
  if(n!==5)document.getElementById('fv-base-sw').style.display='flex';
  document.querySelectorAll('#fv-base-sw .fv-mc-btn').forEach(b=>b.classList.toggle('on',b.textContent.toLowerCase()===bk));
  fetch('/nallamala_boundary').then(r=>r.json()).then(d=>{
    if(!d.error)L.geoJSON(d,{style:{color:'#00d4aa',weight:2,fillOpacity:.04,dashArray:'5 3'}}).addTo(fvMap);
  }).catch(()=>{});
  if(n===1)_fvPanel1();else if(n===2)_fvPanel2();else if(n===3)_fvPanel3();
  else if(n===5)_fvPanel5();else if(n===6)_fvPanel6();
  if(n!==3)fvMap.on('click',e=>{handleClick(e.latlng.lat,e.latlng.lng);if(n===5)setTimeout(()=>_fvPanel5Rerender(),300);});
  _fvCloneOverlays(n);
}
function fvSwitchBase(key,btn){
  if(!fvMap||!fvMapBase)return;fvMap.removeLayer(fvMapBase);
  fvMapBase=baseTile(BASE_TILES[key]||BASE_TILES.osm);fvMapBase.addTo(fvMap);
  document.querySelectorAll('#fv-base-sw .fv-mc-btn').forEach(b=>b.classList.toggle('on',b===btn));
}
function _fvPanel1(){
  fetch('/india_boundary').then(r=>r.json()).then(d=>{if(!d.error)L.geoJSON(d,{style:{color:'#3b82f6',weight:.8,fillOpacity:0}}).addTo(fvMap);}).catch(()=>{});
  fetchDigipinGrid(cells=>{
    const layers=[];
    cells.forEach(c=>{
      const rect=L.rectangle([[c.lat_min,c.lon_min],[c.lat_max,c.lon_max]],{color:'#00d4aa',weight:.8,fillColor:'transparent',fillOpacity:0,dashArray:'2 4',interactive:true});
      rect.bindTooltip(`<b style="color:#00d4aa;letter-spacing:2px">${c.digipin}</b><br><span style="color:#4a6d8a;font-size:10px">${c.center_lat.toFixed(5)}°N ${c.center_lon.toFixed(5)}°E</span>`,{sticky:true,direction:'top'});
      rect.on('click',e=>{L.DomEvent.stopPropagation(e);handleClick(c.center_lat,c.center_lon);});layers.push(rect);
    });
    L.layerGroup(layers).addTo(fvMap);
    let fvHM=null,fvHT=null;
    fvMap.on('mousemove',e=>{clearTimeout(fvHT);fvHT=setTimeout(()=>{
      fetch('/encode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat:e.latlng.lat,lon:e.latlng.lng,precision:10})})
      .then(r=>r.json()).then(d=>{if(d.error)return;if(fvHM)fvMap.removeLayer(fvHM);
        fvHM=L.marker([e.latlng.lat,e.latlng.lng],{icon:L.divIcon({className:'',iconAnchor:[52,22],
          html:`<div style="background:rgba(11,15,20,.97);color:#00d4aa;padding:3px 10px;border-radius:2px;font-family:monospace;font-size:11px;border:1px solid #00d4aa;letter-spacing:3px;white-space:nowrap">${d.digipin}</div>`
        })}).addTo(fvMap);}).catch(()=>{});},60);});
    fvMap.on('mouseout',()=>{if(fvHM){fvMap.removeLayer(fvHM);fvHM=null;}});
  });
}
function _fvPanel2(){
  document.getElementById('fv-lulc-years').style.display='flex';
  fvLulcYearActive=lulcYear;
  document.querySelectorAll('#fv-lulc-years .fv-mc-btn').forEach(b=>b.classList.toggle('on',parseInt(b.textContent)===fvLulcYearActive));
  _fvDrawLulcGrid(fvLulcYearActive);
}
function _fvDrawLulcGrid(yr){
  if(fvLulcLayer){fvMap.removeLayer(fvLulcLayer);fvLulcLayer=null;}
  const layers=[];
  digipinGridCells.forEach(c=>{
    const cls=cellLulcClass(c.digipin,yr),color=LULC_COLORS[cls];
    const rect=L.rectangle([[c.lat_min,c.lon_min],[c.lat_max,c.lon_max]],{color:'rgba(0,0,0,.15)',weight:.4,fillColor:color,fillOpacity:0.75,interactive:true});
    rect.bindTooltip(`<span style="color:${color};font-weight:700;font-size:11px">${LULC_CLASSES[cls]}</span><br><span style="color:#00d4aa;font-size:10px">${c.digipin}</span>`,{sticky:true,direction:'top'});
    rect.on('click',e=>{L.DomEvent.stopPropagation(e);showLulcPopup(c,e.containerPoint);});layers.push(rect);
  });
  fvLulcLayer=L.layerGroup(layers).addTo(fvMap);
}
function fvSetLulcYear(yr,btn){
  fvLulcYearActive=yr;lulcYear=yr;
  document.querySelectorAll('.lulc-year-btn').forEach((b,i)=>b.classList.toggle('active',[1991,2001,2011,2021][i]===yr));
  document.querySelectorAll('#fv-lulc-years .fv-mc-btn').forEach(b=>b.classList.toggle('on',b===btn));
  _fvDrawLulcGrid(yr);redrawLulcGrid();
}
function _fvPanel3(){
  const{layer,ext}=resolveGIBSLayer(satSource);
  L.tileLayer(GIBS(layer,document.getElementById('sat3-date').value,ext),{maxZoom:13,tileSize:256,opacity:.8,errorTileUrl:''}).addTo(fvMap);
  if(lastLat){
    fetch('/encode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lat:lastLat,lon:lastLon,precision:10})})
    .then(r=>r.json()).then(e2=>{if(e2.error)return;
      fetch('/decode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({digipin:e2.digipin})})
      .then(r=>r.json()).then(d=>{if(d.error)return;
        L.rectangle([[d.lat_min,d.lon_min],[d.lat_max,d.lon_max]],{color:'#00d4aa',weight:3,fillColor:'#00d4aa',fillOpacity:.15}).addTo(fvMap);
        L.circleMarker([d.center_lat,d.center_lon],{radius:5,color:'#ef4444',fillColor:'#ef4444',fillOpacity:1,weight:2}).bindPopup(`<b style="color:#00d4aa">${e2.digipin}</b><br>${d.center_lat.toFixed(5)}°N<br>${d.center_lon.toFixed(5)}°E`).addTo(fvMap);
        fvMap.setView([d.center_lat,d.center_lon],16);
      });
    });
  }
}
function _fvPanel5(){
  if(cdCells.length){
    const{layer,ext}=resolveGIBSLayer(satSource);
    L.tileLayer(GIBS(layer,document.getElementById('d1').value,ext),{maxZoom:13,tileSize:256,opacity:.15,errorTileUrl:''}).addTo(fvMap);
  }
  document.getElementById('fv-cd-period').style.display='block';
  document.getElementById('fv-cd-period').textContent=document.getElementById('cd-period').textContent;
  fvMap.on('moveend zoomend resize',()=>_fvPanel5Rerender());
  requestAnimationFrame(()=>requestAnimationFrame(()=>_fvPanel5Rerender()));
}
function _fvPanel5Rerender(){
  if(!cdCells.length||!fvMap)return;
  const el=document.getElementById('fv-map-wrap'),W=el.clientWidth,H=el.clientHeight;
  const cv=document.getElementById('fv-cd-canvas');
  cv.style.display='block';cv.width=W;cv.height=H;cv.style.width=W+'px';cv.style.height=H+'px';
  const ctx=cv.getContext('2d');ctx.clearRect(0,0,W,H);
  cdCells.forEach(c=>{
    const sw=fvMap.latLngToContainerPoint([c.lat_min,c.lon_min]),ne=fvMap.latLngToContainerPoint([c.lat_max,c.lon_max]);
    const x0=Math.round(sw.x),y0=Math.round(ne.y),cW=Math.round(ne.x-sw.x),cH=Math.round(sw.y-ne.y);
    if(cW<1||cH<1||x0>W||y0>H||x0+cW<0||y0+cH<0)return;
    c.pixels.forEach((pr,ri)=>pr.forEach((px,ci)=>{
      ctx.fillStyle=px.color;
      ctx.fillRect(Math.round(x0+ci*cW/N_PIXELS),Math.round(y0+ri*cH/N_PIXELS),Math.ceil(cW/N_PIXELS)+1,Math.ceil(cH/N_PIXELS)+1);
    }));
    if(cW>12){ctx.strokeStyle='rgba(0,0,0,.2)';ctx.lineWidth=.5;ctx.strokeRect(x0,y0,cW,cH);}
  });
}
function _fvPanel6(){
  const{layer,ext}=resolveGIBSLayer(satSource);
  L.tileLayer(GIBS(layer,document.getElementById('d1').value,ext),{maxZoom:13,tileSize:256,opacity:.45,errorTileUrl:''}).addTo(fvMap);
  const fy=parseInt(document.getElementById('d0').value),ty=parseInt(document.getElementById('d1').value);
  fetch('/alert_scan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({from_year:fy,to_year:ty})})
  .then(r=>r.json()).then(d=>{
    if(!fvMap)return;
    const SC={ACTIVE:'#ef4444',WARNING:'#f97316',WATCH:'#eab308'};
    d.alerts.forEach(a=>{
      const R=7+Math.sqrt(a.area_ha)*0.22,sc=SC[a.severity],cb=Math.round(a.confidence*100);
      L.circleMarker([a.lat,a.lon],{radius:R*2.2,color:sc,fillColor:sc,fillOpacity:.04,weight:.8,dashArray:'3 3'}).addTo(fvMap);
      L.circleMarker([a.lat,a.lon],{radius:R,color:a.color,fillColor:a.color,
        fillOpacity:a.severity==='ACTIVE'?0.75:a.severity==='WARNING'?0.55:0.38,weight:1.8})
        .bindPopup(`<div style="font-family:'JetBrains Mono',monospace;min-width:250px;line-height:1">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
            <span style="color:${a.color};font-weight:700;font-size:12px">${a.type.replace('_',' ')}</span>
            <span style="background:${sc};color:#000;font-size:10px;font-weight:700;padding:1px 7px;border-radius:2px">${a.severity}</span>
          </div>
          <div style="width:100%;height:4px;background:rgba(255,255,255,.08);border-radius:2px;margin-bottom:8px">
            <div style="width:${cb}%;height:100%;background:${a.color};border-radius:2px"></div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:3px 12px;margin-bottom:8px">
            <span style="color:#4a6d8a;font-size:10px">Area</span><span style="color:${a.color};font-weight:700;font-size:10px">${a.area_ha} ha</span>
            <span style="color:#4a6d8a;font-size:10px">Confidence</span><span style="color:${a.color};font-weight:700;font-size:10px">${a.confidence_pct}</span>
            <span style="color:#4a6d8a;font-size:10px">NDVI Drop</span><span style="color:#f97316;font-weight:700;font-size:10px">${a.evidence.ndvi_drop}</span>
          </div>
          <div style="border-top:1px solid #1a2f45;padding-top:5px;color:#fbbf24;font-size:10px;line-height:1.6">${a.action}</div>
        </div>`,{maxWidth:280}).addTo(fvMap);
    });
    fvMap.fitBounds([[14.7,78.3],[16.9,80.3]],{padding:[20,20]});
  }).catch(()=>{});
}
function _fvCloneOverlays(n){
  const c=document.getElementById('fv-overlays');c.innerHTML='';
  c.style.cssText='position:absolute;inset:0;pointer-events:none;z-index:600';
  const add=h=>{const d=document.createElement('div');d.innerHTML=h;c.appendChild(d.firstElementChild);};
  if(n===1)add(`<div style="position:absolute;top:10px;right:10px;background:rgba(11,15,20,.9);border:1px solid var(--border);padding:5px 10px;border-radius:4px;font-size:.6rem;color:var(--muted)">PREC-${GRID_PREC} · ${digipinGridCells.length} CELLS · Click any cell</div>`);
  if(n===2)add(`<div style="position:absolute;bottom:14px;left:14px;background:rgba(11,15,20,.97);border:1px solid var(--border);padding:9px 12px;border-radius:5px;font-size:.62rem">${LULC_CLASSES.map((cl,i)=>`<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px"><div style="width:13px;height:13px;background:${LULC_COLORS[i]};border-radius:1px;flex-shrink:0"></div>${cl}</div>`).join('')}</div>`);
  if(n===5){
    const CD=[['#1a5c2a','Stable Forest'],['#dc2626','Forest → Agriculture'],['#7f1d1d','Forest → Urban'],
      ['#ea580c','Forest → Scrub/Bare'],['#2563eb','Non-Forest → Forest'],['#f59e0b','Agri → Urban'],
      ['#d4e157','Stable Agriculture'],['#a21caf','Urban (Persistent)'],['#374151','No Significant Change']];
    add(`<div style="position:absolute;bottom:14px;left:14px;background:rgba(11,15,20,.97);border:1px solid var(--border);padding:9px 12px;border-radius:5px;font-size:.62rem;min-width:180px">
      <div style="color:var(--muted);font-size:.5rem;letter-spacing:1px;margin-bottom:6px">CHANGE TYPE</div>
      ${CD.map(([c,l])=>`<div style="display:flex;align-items:center;gap:7px;margin-bottom:4px"><div style="width:13px;height:11px;background:${c};border-radius:1px;flex-shrink:0"></div><span style="color:var(--text);font-size:.58rem">${l}</span></div>`).join('')}
    </div>`);
    add(`<div style="position:absolute;top:10px;right:10px;background:rgba(11,15,20,.97);border:1px solid var(--border);padding:8px 12px;border-radius:5px;font-size:.62rem;line-height:2.2;min-width:160px">
      <div style="color:var(--muted);font-size:.5rem;letter-spacing:1px;margin-bottom:3px">CHANGE STATS</div>
      ${[['Stable Forest','cds-stable','#1a5c2a'],['Forest Loss','cds-loss','#dc2626'],['Forest Gain','cds-gain','#2563eb'],['Urban Expand','cds-urban','#f59e0b'],['Dominant','cds-dom','#c8daea']].map(([k,id,col])=>`<div style="display:flex;justify-content:space-between;gap:16px"><span style="color:var(--muted)">${k}</span><span style="font-weight:700;color:${col}">${document.getElementById(id).textContent}</span></div>`).join('')}
    </div>`);
  }
  if(n===6)add(`<div style="position:absolute;bottom:14px;right:14px;background:rgba(11,15,20,.95);border:1px solid var(--border);padding:8px 12px;border-radius:5px;font-size:.62rem">
    ${[['#ef4444','Critical'],['#f97316','High'],['#eab308','Moderate'],['#22c55e','Low']].map(([c,l])=>`<div style="display:flex;align-items:center;gap:7px;margin-bottom:5px"><div style="width:9px;height:9px;border-radius:50%;background:${c};flex-shrink:0"></div><span>${l}</span></div>`).join('')}
  </div>`);
}
function closeFullView(){
  document.getElementById('fv-overlay').classList.remove('active');
  if(fvMap){fvMap.remove();fvMap=null;fvMapBase=null;fvLulcLayer=null;}
  document.getElementById('fv-cd-canvas').style.display='none';
  fvCurrentPanel=0;
  setTimeout(()=>{renderCdCanvas();[m1,m2,m3,m5,m6].forEach(m=>m.invalidateSize());},100);
}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&fvCurrentPanel)closeFullView();});
</script>
</body>
</html>"""

# ── ROUTES ────────────────────────────────────────────────────
@app.route("/")
def home(): return HTML

@app.route("/encode", methods=["POST"])
def encode():
    try:
        d=request.get_json()
        dp=encode_digipin(float(d['lat']),float(d['lon']),int(d.get('precision',10)))
        return jsonify({"digipin":dp}) if dp else (jsonify({"error":"Out of bounds"}),400)
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/decode", methods=["POST"])
def decode():
    try:
        r=decode_digipin(request.get_json().get('digipin',''))
        return jsonify(r) if r else (jsonify({"error":"Invalid DIGIPIN"}),400)
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/nallamala_boundary")
def nallamala_boundary():
    return jsonify(NALLAMALA_GEOJSON) if NALLAMALA_GEOJSON else (jsonify({"error":"Shapefile not loaded"}),500)

@app.route("/india_boundary")
def india_boundary():
    return jsonify(INDIA_GEOJSON) if INDIA_GEOJSON else (jsonify({"error":"Shapefile not loaded"}),500)

@app.route("/lulc_matrix", methods=["POST"])
def lulc_matrix():
    try:
        d=request.get_json()
        return jsonify({"matrix":get_lulc_matrix(float(d.get('lat',15.8)),float(d.get('lon',79.3)))})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/lulc_timeseries", methods=["POST"])
def lulc_timeseries():
    try:
        d=request.get_json()
        return jsonify(get_lulc_timeseries(float(d.get('lat',15.8)),float(d.get('lon',79.3))))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/digipin_grid", methods=["POST"])
def digipin_grid():
    try:
        d=request.get_json()
        cells=get_digipin_grid_cells(float(d.get('lat_min',14.8)),float(d.get('lat_max',16.8)),
            float(d.get('lon_min',78.4)),float(d.get('lon_max',80.2)),int(d.get('precision',6)))
        return jsonify({"cells":cells,"count":len(cells)})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/hotspots", methods=["POST"])
def hotspots():
    try:
        d=request.get_json()
        return jsonify({"hotspots":get_hotspots(float(d.get('lat',15.8)),float(d.get('lon',79.3)),
            int(d.get('from_year',2001)),int(d.get('to_year',2021)))})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/cell_pixel_changes", methods=["POST"])
def cell_pixel_changes():
    try:
        d=request.get_json()
        px=get_cell_pixel_changes(float(d.get('lat',15.8)),float(d.get('lon',79.3)),
            int(d.get('from_year',2001)),int(d.get('to_year',2021)))
        return jsonify({"pixels":px,"n":len(px)})
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/classify_encroachment", methods=["POST"])
def classify_enc_route():
    try:
        d=request.get_json()
        return jsonify(classify_encroachment(float(d.get('lat',15.8)),float(d.get('lon',79.3)),
            int(d.get('from_year',2001)),int(d.get('to_year',2021))))
    except Exception as e: return jsonify({"error":str(e)}),500

@app.route("/alert_scan", methods=["POST"])
def alert_scan():
    try:
        d=request.get_json()
        alerts=get_encroachment_alerts(int(d.get('from_year',2001)),int(d.get('to_year',2021)))
        counts={'ACTIVE':0,'WARNING':0,'WATCH':0}; types={}; total_ha=0.0
        for a in alerts:
            counts[a['severity']]=counts.get(a['severity'],0)+1
            types[a['type']]=types.get(a['type'],0)+1
            total_ha+=a['area_ha']
        return jsonify({'alerts':alerts,'count':len(alerts),'counts':counts,
            'type_counts':types,'total_ha':round(total_ha,1),
            'dominant':max(types,key=types.get) if types else '—'})
    except Exception as e: return jsonify({"error":str(e)}),500

if __name__=="__main__":
    app.run(debug=True,host='0.0.0.0',port=5005)