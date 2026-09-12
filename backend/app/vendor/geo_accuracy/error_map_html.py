r"""Self-contained interactive viewer for a Stage D error-map result.

Writes ONE .html file with the satellite image, the heat overlay and every
tile vector embedded (base64 / JSON) - no server, no internet, no framework;
it opens in any browser and works offline.  Pan with the mouse, zoom with the
wheel, hover a tile for its numbers, toggle layers, drag the sliders.
"""
from __future__ import annotations

import base64
import io
import json

import cv2
import numpy as np


def _b64_jpg(rgb, quality=88):
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                           [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode()


def _heat_png_b64(res, vmax):
    """Heat overlay as a transparent PNG at 1/4 resolution (OrRd-like ramp)."""
    from .error_map import heat_grid
    Z, step = heat_grid(res)
    if Z is None:
        return None, step
    t = np.clip(np.nan_to_num(Z, nan=0.0) / vmax, 0, 1)
    # 4-stop ramp: pale sand -> orange -> red -> dark red
    stops = np.array([[255, 247, 236], [253, 187, 132], [227, 74, 51], [127, 0, 0]], float)
    idx = np.clip(t * 3, 0, 2.999)
    lo = np.floor(idx).astype(int)
    fr = (idx - lo)[..., None]
    rgb = (stops[lo] * (1 - fr) + stops[lo + 1] * fr).astype(np.uint8)
    alpha = np.where(np.isnan(Z), 0, 165).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    return base64.b64encode(buf.tobytes()).decode(), step


def write_interactive_html(res, camEN, out_path, title="Error map"):
    p = res.params
    good = res.good
    vmax = max(6.0, float(np.ceil(np.percentile([t["err"] for t in good], 98)))) if good else 8.0
    heat_b64, heat_step = _heat_png_b64(res, vmax)
    H, W = res.sat.shape[:2]
    camx = (camEN[0] - res.origin[0]) / p.gsd
    camy = (res.origin[1] - camEN[1]) / p.gsd

    tiles = [dict(x=round(t["x0"] + t["tile"] / 2, 1), y=round(t["y0"] + t["tile"] / 2, 1),
                  dE=round(t["dE"], 2), dN=round(t["dN"], 2), err=round(t["err"], 2),
                  rad=round(t["radial"], 2), tan=round(t["tangential"], 2),
                  rng=round(t["range"]), resp=round(t["resp"], 3),
                  m=t.get("method", "phase"), ok=bool(t["ok"]))
             for t in res.tiles]
    zones = [dict(band=z[0], n=z[1], err=round(z[2], 2), dE=round(z[3], 2),
                  dN=round(z[4], 2), rad=round(z[5], 2), tan=round(z[6], 2))
             for z in res.zone_summary()]

    data = dict(W=W, H=H, gsd=p.gsd, tile=p.tile, stride=p.stride, vmax=vmax,
                heatStep=heat_step, cam=[round(camx, 1), round(camy, 1)],
                rings=[300, 500, 1000], tiles=tiles, zones=zones)

    html = HTML_TEMPLATE
    html = html.replace("__TITLE__", title)
    html = html.replace("__SAT_B64__", _b64_jpg(res.sat))
    html = html.replace("__HEAT_B64__", heat_b64 or "")
    html = html.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


HTML_TEMPLATE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
 :root{--ink:#1e293b;--muted:#64748b;--line:#e2e8f0;--blue:#2563eb;--bg:#f6f8fb}
 *{box-sizing:border-box;margin:0}
 body{font:13px "Segoe UI",system-ui,sans-serif;color:var(--ink);background:var(--bg);
      display:flex;flex-direction:column;height:100vh;overflow:hidden}
 header{padding:8px 14px;background:#fff;border-bottom:1px solid var(--line);
        display:flex;gap:16px;align-items:center;flex-wrap:wrap}
 header h1{font-size:15px;font-weight:600;margin-right:6px}
 header label{color:var(--muted);display:flex;gap:5px;align-items:center;user-select:none}
 header input[type=range]{width:90px;accent-color:var(--blue)}
 header input[type=checkbox]{accent-color:var(--blue)}
 #hint{color:var(--muted);margin-left:auto}
 main{flex:1;display:flex;min-height:0}
 #wrap{flex:1;position:relative;background:#20242b}
 canvas{position:absolute;inset:0;width:100%;height:100%;cursor:grab}
 canvas:active{cursor:grabbing}
 #tip{position:absolute;pointer-events:none;background:#0f172aee;color:#fff;padding:7px 10px;
      border-radius:6px;font-size:12px;line-height:1.5;display:none;max-width:240px;z-index:5}
 #tip b{color:#fdba74}
 aside{width:300px;background:#fff;border-left:1px solid var(--line);padding:12px;overflow:auto}
 aside h2{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;
          letter-spacing:.04em;margin:10px 0 6px}
 table{border-collapse:collapse;width:100%;font-size:12px}
 td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:right}
 th{color:var(--muted);font-weight:600}
 td:first-child,th:first-child{text-align:left}
 #bar{height:12px;border-radius:6px;margin:4px 0 2px;
      background:linear-gradient(90deg,#fff7ec,#fdbb84,#e34a33,#7f0000)}
 .axis{display:flex;justify-content:space-between;color:var(--muted);font-size:11px}
 .note{color:var(--muted);font-size:11.5px;line-height:1.5;margin-top:8px}
</style></head><body>
<header>
 <h1>__TITLE__</h1>
 <label><input type="checkbox" id="cbHeat" checked> heat map</label>
 <label><input type="checkbox" id="cbArrows" checked> arrows</label>
 <label><input type="checkbox" id="cbGray" checked> gray satellite</label>
 <label>heat opacity <input type="range" id="rgOp" min="0" max="100" value="62"></label>
 <label>arrow scale <input type="range" id="rgSc" min="2" max="40" value="15"></label>
 <span id="hint">drag = pan &nbsp; wheel = zoom &nbsp; hover a tile for its numbers</span>
</header>
<main>
 <div id="wrap"><canvas id="cv"></canvas><div id="tip"></div></div>
 <aside>
  <h2>error scale (m)</h2>
  <div id="bar"></div><div class="axis"><span>0</span><span id="vmax"></span></div>
  <h2>zone summary (medians)</h2>
  <table id="zt"><tr><th>band</th><th>n</th><th>err</th><th>rad</th><th>tan</th></tr></table>
  <h2>how to read it</h2>
  <div class="note">Each arrow / colour cell is one matched tile: how far our
  rectified photo sits from the satellite there = the geolocation error, as a
  vector (dE, dN).<br><br><b>radial</b> (along the camera sightline) points to
  DEM height error; <b>tangential</b> (across it) points to pose/calibration.
  Grey dots are tiles with no reliable match.<br><br>A constant offset shared
  by every arrow may belong to the satellite basemap itself (a few m).</div>
 </aside>
</main>
<script>
const D=__DATA__;
const sat=new Image(),heat=new Image();let ready=0;
sat.onload=heat.onload=()=>{if(++ready>=need)draw()};
sat.src="data:image/jpeg;base64,__SAT_B64__";
const need="__HEAT_B64__"?2:1;
if("__HEAT_B64__")heat.src="data:image/png;base64,__HEAT_B64__";
const cv=document.getElementById("cv"),ctx=cv.getContext("2d"),tip=document.getElementById("tip");
let sc,ox,oy;                       // view transform: screen = map*sc + (ox,oy)
function fit(){const w=cv.clientWidth,h=cv.clientHeight;
 if(!w||!h){requestAnimationFrame(fit);return;}   // pane not displayed yet
 cv.width=w;cv.height=h;
 sc=Math.min(w/D.W,h/D.H)*0.98;ox=(w-D.W*sc)/2;oy=(h-D.H*sc)/2;draw();}
addEventListener("resize",fit);
const gray=document.createElement("canvas");
function grayify(){gray.width=D.W;gray.height=D.H;const g=gray.getContext("2d");
 g.drawImage(sat,0,0);const im=g.getImageData(0,0,D.W,D.H),d=im.data;
 for(let i=0;i<d.length;i+=4){const v=.3*d[i]+.59*d[i+1]+.11*d[i+2];d[i]=d[i+1]=d[i+2]=v;}
 g.putImageData(im,0,0);}
let grayed=false;
function draw(){
 if(!sat.complete)return;
 if(ui.cbGray.checked&&!grayed){grayify();grayed=true;}
 ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle="#20242b";ctx.fillRect(0,0,cv.width,cv.height);
 ctx.setTransform(sc,0,0,sc,ox,oy);
 ctx.drawImage(ui.cbGray.checked?gray:sat,0,0);
 if(ui.cbHeat.checked&&heat.src){ctx.globalAlpha=ui.rgOp.value/100;
  ctx.drawImage(heat,0,0,D.W/D.heatStep,D.H/D.heatStep,0,0,D.W,D.H);ctx.globalAlpha=1;}
 ctx.strokeStyle="#2563eb";ctx.setLineDash([6/sc,5/sc]);ctx.lineWidth=1.2/sc;
 ctx.fillStyle="#2563eb";
 for(const r of D.rings){ctx.beginPath();ctx.arc(D.cam[0],D.cam[1],r/D.gsd,0,7);ctx.stroke();
  ctx.font=`${12/sc}px Segoe UI`;ctx.fillText(r+" m",D.cam[0]+4/sc,D.cam[1]-r/D.gsd-4/sc);}
 ctx.setLineDash([]);
 ctx.beginPath();ctx.moveTo(D.cam[0],D.cam[1]-9/sc);ctx.lineTo(D.cam[0]-8/sc,D.cam[1]+7/sc);
 ctx.lineTo(D.cam[0]+8/sc,D.cam[1]+7/sc);ctx.closePath();
 ctx.fillStyle="#2563eb";ctx.fill();ctx.strokeStyle="#fff";ctx.lineWidth=1.5/sc;ctx.stroke();
 if(ui.cbArrows.checked){const k=+ui.rgSc.value;
  for(const t of D.tiles){ if(!t.ok){ctx.fillStyle="#94a3b8";
    ctx.fillRect(t.x-1.5/sc,t.y-1.5/sc,3/sc,3/sc);continue;}
   const c=ramp(t.err/D.vmax);ctx.strokeStyle=c;ctx.fillStyle=c;ctx.lineWidth=2.2/sc;
   const x2=t.x+t.dE*k/D.gsd,y2=t.y-t.dN*k/D.gsd;
   ctx.beginPath();ctx.moveTo(t.x,t.y);ctx.lineTo(x2,y2);ctx.stroke();
   const a=Math.atan2(y2-t.y,x2-t.x),s=7/sc;
   ctx.beginPath();ctx.moveTo(x2,y2);
   ctx.lineTo(x2-s*Math.cos(a-.45),y2-s*Math.sin(a-.45));
   ctx.lineTo(x2-s*Math.cos(a+.45),y2-s*Math.sin(a+.45));ctx.closePath();ctx.fill();}}
}
function ramp(t){t=Math.max(0,Math.min(1,t));
 const st=[[255,180,90],[249,115,22],[220,38,38],[127,0,0]];
 const i=Math.min(2,Math.floor(t*3)),f=t*3-i;
 const c=st[i].map((v,j)=>Math.round(v*(1-f)+st[i+1][j]*f));
 return`rgb(${c[0]},${c[1]},${c[2]})`;}
const ui={};for(const id of["cbHeat","cbArrows","cbGray","rgOp","rgSc"]){
 ui[id]=document.getElementById(id);ui[id].addEventListener("input",draw);}
let drag=null;
cv.addEventListener("mousedown",e=>drag=[e.clientX,e.clientY]);
addEventListener("mouseup",()=>drag=null);
cv.addEventListener("mousemove",e=>{
 if(drag){ox+=e.clientX-drag[0];oy+=e.clientY-drag[1];drag=[e.clientX,e.clientY];draw();return;}
 const mx=(e.offsetX-ox)/sc,my=(e.offsetY-oy)/sc;let best=null,bd=1e9;
 for(const t of D.tiles){const d=Math.hypot(t.x-mx,t.y-my);
  if(d<bd){bd=d;best=t;}}
 if(best&&bd<D.tile/D.gsd/2){
  tip.style.display="block";tip.style.left=(e.offsetX+16)+"px";tip.style.top=(e.offsetY+10)+"px";
  tip.innerHTML=best.ok?
   `<b>${best.err.toFixed(2)} m</b> @ ${best.rng} m range<br>`+
   `dE ${best.dE>=0?"+":""}${best.dE}&nbsp;&nbsp;dN ${best.dN>=0?"+":""}${best.dN}<br>`+
   `radial ${best.rad} &middot; tangential ${best.tan}<br>`+
   (best.m==="mi"?`MI rescue &middot; sharpness ${best.resp}`:`peak ${best.resp}`):
   `no reliable lock here<br>@ ${best.rng} m range (peak ${best.resp})`;
 }else tip.style.display="none";});
cv.addEventListener("wheel",e=>{e.preventDefault();
 const f=e.deltaY<0?1.18:1/1.18,mx=(e.offsetX-ox)/sc,my=(e.offsetY-oy)/sc;
 sc*=f;ox=e.offsetX-mx*sc;oy=e.offsetY-my*sc;draw();},{passive:false});
document.getElementById("vmax").textContent=D.vmax+"+";
const zt=document.getElementById("zt");
for(const z of D.zones){const r=zt.insertRow();
 for(const v of[z.band,z.n,z.err,z.rad,z.tan])r.insertCell().textContent=v;}
fit();
</script></body></html>
"""
