#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generator 20 mockupów podstrony "Analiza cen wg metrażu".
Każdy mockup to samodzielny plik HTML (dane wbudowane inline) -> docs/mockups/NN-*.html
Uruchom: python3 docs/mockups/generate.py  (najpierw compute_stats.py)
"""
import json, pathlib

HERE = pathlib.Path(__file__).resolve().parent
S = json.load(open(HERE / 'stats.json', encoding='utf-8'))
DATA_JSON = json.dumps(S, ensure_ascii=False)

CDN = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'

# ---------------------------------------------------------------------------
# Wspólna biblioteka JS: budowniczowie wykresów operujący na globalnym `S`.
# Każdy mockup wybiera potrzebne wykresy. Funkcje są odporne na brak elementu.
# ---------------------------------------------------------------------------
LIB = r"""
const S = __DATA__;
const PLN = n => (n==null?'—':Math.round(n).toLocaleString('pl-PL')+' zł');
const PPM = n => (n==null?'—':(Math.round(n*10)/10).toLocaleString('pl-PL')+' zł/m²');
function el(id){return document.getElementById(id);}
function cssVar(n,f){const v=getComputedStyle(document.body).getPropertyValue(n).trim();return v||f;}
const RAMP=['#00c853','#64dd17','#aeea00','#ffd600','#ffab00','#ff6f00','#ff3d00','#d50000','#c51162','#aa00ff','#7c4dff','#6200ea','#311b92'];
function rampFor(vals){const mn=Math.min(...vals),mx=Math.max(...vals);return vals.map(v=>{const t=mx===mn?0.5:(v-mn)/(mx-mn);return RAMP[Math.round(t*(RAMP.length-1))];});}

function chBrackets(id,key){const c=el(id);if(!c)return;const L=S.area_brackets.map(b=>b.label);
 const v=S.area_brackets.map(b=>b[key||'median_ppm']);
 new Chart(c,{type:'bar',data:{labels:L,datasets:[{data:v,backgroundColor:rampFor(v),borderRadius:6}]},
  options:{plugins:{legend:{display:false},tooltip:{callbacks:{label:i=>(key==='median_price'?PLN(i.raw):PPM(i.raw))}}},
   scales:{y:{beginAtZero:true,grid:{color:'rgba(128,128,128,.12)'}},x:{grid:{display:false}}}}});}

function chBracketsCount(id){const c=el(id);if(!c)return;
 new Chart(c,{type:'bar',data:{labels:S.area_brackets.map(b=>b.label),datasets:[{data:S.area_brackets.map(b=>b.count),
  backgroundColor:cssVar('--accent','#667eea'),borderRadius:6}]},
  options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{grid:{color:'rgba(128,128,128,.12)'}},y:{grid:{display:false}}}}});}

function chPpmHist(id){const c=el(id);if(!c)return;
 new Chart(c,{type:'bar',data:{labels:S.ppm_hist.labels,datasets:[{data:S.ppm_hist.counts,
  backgroundColor:cssVar('--accent','#667eea'),borderRadius:3}]},
  options:{plugins:{legend:{display:false},tooltip:{callbacks:{title:i=>i[0].label+' zł/m²'}}},
   scales:{y:{beginAtZero:true,grid:{color:'rgba(128,128,128,.12)'}},x:{grid:{display:false}}}}});}

function chScatter(id){const c=el(id);if(!c)return;
 new Chart(c,{type:'scatter',data:{datasets:[{data:S.scatter.map(p=>({x:p[0],y:p[1]})),
  backgroundColor:'rgba(102,126,234,.45)',pointRadius:3}]},
  options:{plugins:{legend:{display:false},tooltip:{callbacks:{label:i=>i.raw.x+' m² · '+PLN(i.raw.y)}}},
   scales:{x:{title:{display:true,text:'Powierzchnia (m²)'},grid:{color:'rgba(128,128,128,.1)'}},
           y:{title:{display:true,text:'Cena (zł)'},grid:{color:'rgba(128,128,128,.1)'}}}}});}

function chDistricts(id,key,n){const c=el(id);if(!c)return;const D=S.districts.slice(0,n||12);
 const v=D.map(d=>d[key||'median_ppm']);
 new Chart(c,{type:'bar',data:{labels:D.map(d=>d.name),datasets:[{data:v,backgroundColor:rampFor(v),borderRadius:5}]},
  options:{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:i=>(key==='median_price'?PLN(i.raw):PPM(i.raw))}}},
   scales:{x:{grid:{color:'rgba(128,128,128,.12)'}},y:{grid:{display:false}}}}});}

function chTrend(id){const c=el(id);if(!c)return;
 new Chart(c,{type:'line',data:{labels:S.trend.map(t=>t.month),datasets:[
   {label:'Mediana zł/m²',data:S.trend.map(t=>t.median_ppm),borderColor:'#667eea',backgroundColor:'rgba(102,126,234,.15)',fill:true,tension:.3,yAxisID:'y'},
   {label:'Mediana ceny',data:S.trend.map(t=>t.median_price),borderColor:'#f59e0b',tension:.3,yAxisID:'y1'}]},
  options:{plugins:{legend:{position:'bottom'}},scales:{y:{position:'left',grid:{color:'rgba(128,128,128,.1)'}},
   y1:{position:'right',grid:{display:false}}}}});}

function chRooms(id){const c=el(id);if(!c)return;
 new Chart(c,{type:'bar',data:{labels:S.rooms.map(r=>r.rooms+' pok.'),datasets:[
   {label:'Mediana ceny',data:S.rooms.map(r=>r.median_price),backgroundColor:'#667eea',borderRadius:5,yAxisID:'y'},
   {label:'zł/m²',data:S.rooms.map(r=>r.median_ppm),backgroundColor:'#f59e0b',borderRadius:5,yAxisID:'y1'}]},
  options:{plugins:{legend:{position:'bottom'}},scales:{y:{position:'left',beginAtZero:true},y1:{position:'right',grid:{display:false}}}}});}

function chRadarDistricts(id){const c=el(id);if(!c)return;const D=S.districts.slice(0,7);
 new Chart(c,{type:'radar',data:{labels:D.map(d=>d.name),datasets:[{label:'zł/m²',data:D.map(d=>d.median_ppm),
  borderColor:'#667eea',backgroundColor:'rgba(102,126,234,.25)'}]},options:{plugins:{legend:{display:false}}}});}

function chDoughnutBrackets(id){const c=el(id);if(!c)return;
 new Chart(c,{type:'doughnut',data:{labels:S.area_brackets.map(b=>b.label),datasets:[{data:S.area_brackets.map(b=>b.count),
  backgroundColor:RAMP.slice(0,S.area_brackets.length)}]},options:{plugins:{legend:{position:'right'}}}});}

// HTML heatmapa dzielnica × przedział (mediana zł/m²)
function renderHeatmap(id){const box=el(id);if(!box)return;const H=S.heatmap;
 let all=[];H.ppm.forEach(r=>r.forEach(v=>{if(v!=null)all.push(v);}));
 const mn=Math.min(...all),mx=Math.max(...all);
 const col=v=>{if(v==null)return 'background:#eee;color:#bbb';const t=(v-mn)/(mx-mn||1);
   const r=Math.round(40+t*200),g=Math.round(180-t*150),b=Math.round(120-t*80);
   return `background:rgb(${r},${g},${b});color:${t>.55?'#fff':'#222'}`;};
 let h='<table class="hm"><thead><tr><th></th>'+H.brackets.map(b=>'<th>'+b+'</th>').join('')+'</tr></thead><tbody>';
 H.districts.forEach((d,i)=>{h+='<tr><th>'+d+'</th>'+H.ppm[i].map(v=>`<td style="${col(v)}">${v==null?'·':Math.round(v)}</td>`).join('')+'</tr>';});
 h+='</tbody></table>';box.innerHTML=h;}

// Tabela przedziałów
function renderBracketTable(id){const t=el(id);if(!t)return;
 t.innerHTML='<table class="tbl"><thead><tr><th>Metraż</th><th>Ofert</th><th>Mediana</th><th>zł/m²</th><th>Zakres (25–75%)</th></tr></thead><tbody>'+
 S.area_brackets.map(b=>`<tr><td><b>${b.label}</b></td><td>${b.count}</td><td>${PLN(b.median_price)}</td><td>${PPM(b.median_ppm)}</td><td>${PLN(b.p25_price)} – ${PLN(b.p75_price)}</td></tr>`).join('')+'</tbody></table>';}

// Tabela dzielnic
function renderDistrictTable(id,n){const t=el(id);if(!t)return;
 t.innerHTML='<table class="tbl"><thead><tr><th>Dzielnica</th><th>Ofert</th><th>Mediana</th><th>śr. m²</th><th>zł/m²</th></tr></thead><tbody>'+
 S.districts.slice(0,n||20).map(d=>`<tr><td><b>${d.name}</b></td><td>${d.count}</td><td>${PLN(d.median_price)}</td><td>${d.median_area} m²</td><td>${PPM(d.median_ppm)}</td></tr>`).join('')+'</tbody></table>';}

// Kalkulator: wpisz metraż -> szacowana cena (z mediany zł/m² najbliższego przedziału)
function initCalc(areaId,distId,outId,ppmId){const a=el(areaId);if(!a)return;
 const d=distId?el(distId):null;
 if(d){d.innerHTML='<option value="">— cały rynek —</option>'+S.districts.map(x=>`<option value="${x.median_ppm}">${x.name} (${PPM(x.median_ppm)})</option>`).join('');}
 function calc(){const area=parseFloat(a.value)||0;let ppm;
   if(d&&d.value){ppm=parseFloat(d.value);}else{const b=S.area_brackets.find(b=>area>=b.min&&area<b.max)||S.area_brackets[S.area_brackets.length-1];ppm=b.median_ppm;}
   if(el(ppmId))el(ppmId).textContent=PPM(ppm);
   if(el(outId))el(outId).textContent=area?PLN(area*ppm):'—';}
 a.addEventListener('input',calc);if(d)d.addEventListener('change',calc);calc();}
"""

def lib_js():
    return LIB.replace('__DATA__', DATA_JSON)

# Skróty do liczb na potrzeby statycznego HTML
O = S['overall']; M = S['meta']

def page(fname, title, head_css, body, init_js, gallery_note):
    """Składa kompletny, samodzielny plik HTML."""
    html = f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
{CDN}
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
table.tbl{{width:100%;border-collapse:collapse;font-size:14px}}
table.tbl th,table.tbl td{{padding:9px 10px;text-align:left;border-bottom:1px solid rgba(128,128,128,.18)}}
table.tbl th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;opacity:.7}}
table.tbl tr:hover td{{background:rgba(128,128,128,.06)}}
table.hm{{border-collapse:collapse;font-size:12px;width:100%}}
table.hm th{{padding:6px 8px;font-weight:600;font-size:11px}}
table.hm thead th{{writing-mode:initial}}
table.hm tbody th{{text-align:right;white-space:nowrap}}
table.hm td{{padding:8px 6px;text-align:center;font-weight:600;border-radius:3px}}
canvas{{max-width:100%}}
{head_css}
</style></head>
<body>
{body}
<script>{lib_js()}</script>
<script>{init_js}</script>
</body></html>"""
    (HERE / fname).write_text(html, encoding='utf-8')
    return dict(file=fname, title=title, note=gallery_note)

MOCKUPS = []
def add(*a): MOCKUPS.append(page(*a))

# Wspólne fragmenty -----------------------------------------------------------
RIBBON = lambda n,name: f'<div class="ribbon">MOCKUP #{n:02d} · {name}</div>'

def hero_nums():
    return (O['median_price'], O['median_ppm'], O['median_area'], M['analyzed'], M['coverage_pct'])

# ============================================================================
# 01 — Klasyczny Dashboard (gradient fioletowy, spójny z resztą serwisu)
# ============================================================================
mp,ppm,ar,n,cov = hero_nums()
add('01-klasyczny-dashboard.html','01 · Klasyczny Dashboard', """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;padding:20px;--accent:#667eea}
.container{max-width:1400px;margin:0 auto}
.ribbon{position:fixed;top:0;right:0;background:#111;color:#fff;font-size:11px;padding:5px 12px;border-bottom-left-radius:8px;z-index:99}
header{background:#fff;padding:24px;border-radius:14px;box-shadow:0 4px 6px rgba(0,0,0,.1);margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
header h1{color:#667eea;font-size:26px}
.back-link{color:#667eea;text-decoration:none;padding:9px 18px;border:2px solid #667eea;border-radius:8px;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin-bottom:20px}
.card{background:#fff;padding:20px;border-radius:14px;box-shadow:0 2px 4px rgba(0,0,0,.1)}
.card h3{color:#888;font-size:13px;font-weight:600;margin-bottom:8px}
.card .v{font-size:32px;font-weight:800;color:#333}
.card .s{font-size:13px;color:#10b981;margin-top:6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.panel{background:#fff;padding:22px;border-radius:14px;box-shadow:0 2px 4px rgba(0,0,0,.1);margin-bottom:20px}
.panel h2{font-size:18px;color:#333;margin-bottom:14px}
.cw{height:320px;position:relative}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(1,'Klasyczny Dashboard')}
<div class="container">
 <header><h1>📐 Ceny wg metrażu — Lublin</h1><a class="back-link" href="../index.html">← Mapa</a></header>
 <div class="cards">
  <div class="card"><h3>MEDIANA CENY</h3><div class="v">{mp:,} zł</div><div class="s">{n} ofert z metrażem</div></div>
  <div class="card"><h3>MEDIANA zł/m²</h3><div class="v">{ppm} zł</div><div class="s">widełki {O['p25_ppm']}–{O['p75_ppm']}</div></div>
  <div class="card"><h3>MEDIANA METRAŻU</h3><div class="v">{ar} m²</div><div class="s">pokrycie {cov}% bazy</div></div>
  <div class="card"><h3>P10–P90 CENY</h3><div class="v" style="font-size:24px">{O['p10_price']:,}–{O['p90_price']:,}</div><div class="s">80% rynku</div></div>
 </div>
 <div class="panel"><h2>💰 Cena za m² wg przedziału metrażu</h2><div class="cw"><canvas id="c1"></canvas></div></div>
 <div class="grid">
  <div class="panel"><h2>🏷️ Mediana ceny wg przedziału</h2><div class="cw"><canvas id="c2"></canvas></div></div>
  <div class="panel"><h2>📊 Rozkład zł/m²</h2><div class="cw"><canvas id="c3"></canvas></div></div>
 </div>
 <div class="panel"><h2>📈 Powierzchnia vs cena</h2><div class="cw"><canvas id="c4"></canvas></div></div>
 <div class="grid">
  <div class="panel"><h2>🗺️ Dzielnice — zł/m²</h2><div class="cw"><canvas id="c5"></canvas></div></div>
  <div class="panel"><h2>📋 Tabela przedziałów</h2><div id="t1"></div></div>
 </div>
</div>
""", """chBrackets('c1','median_ppm');chBrackets('c2','median_price');chPpmHist('c3');chScatter('c4');chDistricts('c5','median_ppm');renderBracketTable('t1');""",
'Bazowy dashboard w kolorystyce serwisu: karty KPI, słupki przedziałów, scatter, dzielnice, tabela.')

# ============================================================================
# 02 — Dark Pro (ciemny, neonowe akcenty, gęsta siatka)
# ============================================================================
add('02-dark-pro.html','02 · Dark Pro', """
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#e6edf3;padding:18px;--accent:#58a6ff}
.ribbon{position:fixed;top:0;right:0;background:#58a6ff;color:#0d1117;font-weight:700;font-size:11px;padding:5px 12px;border-bottom-left-radius:8px;z-index:99}
.container{max-width:1500px;margin:0 auto}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:10px}
header h1{font-size:24px;color:#58a6ff}
.back-link{color:#8b949e;text-decoration:none;border:1px solid #30363d;padding:8px 14px;border-radius:8px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:18px}
.kpi{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px}
.kpi h3{font-size:11px;letter-spacing:.08em;color:#8b949e;text-transform:uppercase}
.kpi .v{font-size:30px;font-weight:800;margin-top:6px;color:#58a6ff}
.kpi .v.g{color:#3fb950}
.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px}
.panel{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:18px;margin-bottom:16px}
.panel h2{font-size:15px;margin-bottom:12px;color:#e6edf3}
.cw{height:300px;position:relative}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(2,'Dark Pro')}
<div class="container">
 <header><h1>◢ ANALIZA zł/m² — LUBLIN</h1><a class="back-link" href="../index.html">← powrót</a></header>
 <div class="kpis">
  <div class="kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
  <div class="kpi"><h3>Mediana ceny</h3><div class="v g">{mp:,} zł</div></div>
  <div class="kpi"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
  <div class="kpi"><h3>Próbka</h3><div class="v">{n}</div></div>
  <div class="kpi"><h3>Min–Max zł/m²</h3><div class="v" style="font-size:22px">{O['min_ppm']:.0f}–{O['max_ppm']:.0f}</div></div>
 </div>
 <div class="grid">
  <div class="panel"><h2>zł/m² wg przedziału metrażu</h2><div class="cw"><canvas id="c1"></canvas></div></div>
  <div class="panel"><h2>Liczba ofert</h2><div class="cw"><canvas id="c2"></canvas></div></div>
 </div>
 <div class="panel"><h2>Mapa cieplna: dzielnica × metraż (mediana zł/m²)</h2><div id="hm"></div></div>
 <div class="grid">
  <div class="panel"><h2>Powierzchnia vs cena</h2><div class="cw"><canvas id="c4"></canvas></div></div>
  <div class="panel"><h2>Dzielnice</h2><div class="cw"><canvas id="c5"></canvas></div></div>
 </div>
</div>
""", """chBrackets('c1');chBracketsCount('c2');renderHeatmap('hm');chScatter('c4');chDistricts('c5','median_ppm',10);""",
'Ciemny motyw "analityka pro": gęste KPI, heatmapa dzielnica×metraż, scatter — dla power-userów.')

# ============================================================================
# 03 — Glassmorphism
# ============================================================================
add('03-glassmorphism.html','03 · Glassmorphism', """
body{font-family:'Segoe UI',sans-serif;min-height:100vh;padding:22px;color:#fff;background:linear-gradient(135deg,#5b247a,#1bcedf);--accent:#fff}
.ribbon{position:fixed;top:0;right:0;background:rgba(255,255,255,.25);backdrop-filter:blur(8px);color:#fff;font-size:11px;padding:5px 12px;border-bottom-left-radius:8px;z-index:99}
.container{max-width:1300px;margin:0 auto}
header{text-align:center;margin-bottom:24px}
header h1{font-size:30px;font-weight:800;text-shadow:0 2px 12px rgba(0,0,0,.2)}
header p{opacity:.9;margin-top:6px}
.glass{background:rgba(255,255,255,.14);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.25);border-radius:18px;padding:22px;box-shadow:0 8px 32px rgba(0,0,0,.15);margin-bottom:20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:20px}
.kpi .v{font-size:34px;font-weight:800}.kpi h3{font-size:13px;opacity:.85}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.glass h2{margin-bottom:14px;font-size:18px}
.cw{height:300px;position:relative}
.back-link{display:inline-block;margin-top:12px;color:#fff;text-decoration:none;border:1px solid rgba(255,255,255,.5);padding:8px 18px;border-radius:30px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(3,'Glassmorphism')}
<div class="container">
 <header><h1>Ile kosztuje metr w Lublinie?</h1><p>Analiza {n} ofert najmu · pokrycie {cov}% bazy</p>
  <a class="back-link" href="../index.html">← powrót do mapy</a></header>
 <div class="kpis">
  <div class="glass kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
  <div class="glass kpi"><h3>Mediana ceny</h3><div class="v">{mp:,}</div></div>
  <div class="glass kpi"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
  <div class="glass kpi"><h3>Widełki zł/m²</h3><div class="v" style="font-size:24px">{O['p25_ppm']}–{O['p75_ppm']}</div></div>
 </div>
 <div class="glass"><h2>💎 Cena za m² maleje z metrażem</h2><div class="cw"><canvas id="c1"></canvas></div></div>
 <div class="grid">
  <div class="glass"><h2>Udział przedziałów</h2><div class="cw"><canvas id="c2"></canvas></div></div>
  <div class="glass"><h2>Dzielnice (zł/m²)</h2><div class="cw"><canvas id="c3"></canvas></div></div>
 </div>
</div>
""", """Chart.defaults.color='#fff';Chart.defaults.borderColor='rgba(255,255,255,.15)';chBrackets('c1');chDoughnutBrackets('c2');chDistricts('c3','median_ppm',10);""",
'Frosted-glass na żywym gradiencie — efektowny, marketingowy. Centralny KPI + 3 wykresy.')

# ============================================================================
# 04 — Minimal / Whitepaper (raport)
# ============================================================================
add('04-minimal-raport.html','04 · Minimal / Raport', """
body{font-family:Georgia,'Times New Roman',serif;background:#faf9f7;color:#222;padding:40px 20px;line-height:1.65;--accent:#1a1a1a}
.ribbon{position:fixed;top:0;right:0;background:#1a1a1a;color:#fff;font-size:11px;padding:5px 12px;font-family:sans-serif;z-index:99}
.doc{max-width:760px;margin:0 auto}
h1{font-size:34px;font-weight:normal;border-bottom:3px solid #1a1a1a;padding-bottom:14px;margin-bottom:8px}
.sub{font-style:italic;color:#777;margin-bottom:30px}
h2{font-size:22px;margin:34px 0 12px;font-weight:normal}
p{margin-bottom:14px}
.lead{font-size:19px}
.big{font-size:50px;font-weight:bold;font-family:Georgia;display:inline-block;margin:6px 16px 6px 0}
.big small{font-size:15px;color:#888;font-family:sans-serif;display:block;font-weight:normal}
.cw{height:300px;position:relative;margin:18px 0;font-family:sans-serif}
.tbl{font-family:sans-serif}
.back-link{color:#1a1a1a;font-family:sans-serif;font-size:14px}
hr{border:none;border-top:1px solid #ddd;margin:30px 0}
""", f"""
{RIBBON(4,'Minimal / Raport')}
<div class="doc">
 <a class="back-link" href="../index.html">← powrót</a>
 <h1>Cena najmu a metraż</h1>
 <div class="sub">Raport rynku mieszkań w Lublinie · próbka {n} ofert · stan na {M['last_scan'][:10]}</div>
 <p class="lead">Mediana stawki najmu wynosi <b>{mp:,} zł</b> miesięcznie, co przy medianie powierzchni
 <b>{ar} m²</b> daje <b>{ppm} zł za metr kwadratowy</b>. Połowa rynku mieści się w widełkach
 {O['p25_ppm']}–{O['p75_ppm']} zł/m².</p>
 <div>
  <span class="big">{ppm} zł<small>mediana zł/m²</small></span>
  <span class="big">{mp:,} zł<small>mediana ceny</small></span>
  <span class="big">{ar} m²<small>mediana metrażu</small></span>
 </div>
 <hr>
 <h2>Efekt skali</h2>
 <p>Im większe mieszkanie, tym niższa stawka za metr — od ~{S['area_brackets'][0]['median_ppm']} zł/m² dla kawalerek
 do ~{S['area_brackets'][-1]['median_ppm']} zł/m² dla lokali 90 m²+.</p>
 <div class="cw"><canvas id="c1"></canvas></div>
 <h2>Pełne zestawienie przedziałów</h2>
 <div id="t1"></div>
 <h2>Zróżnicowanie dzielnic</h2>
 <div id="t2"></div>
 <hr>
 <p style="font-size:13px;color:#999;font-family:sans-serif">Metodyka: powierzchnia i liczba pokoi wyekstrahowane z treści ogłoszeń
 (regex), cena z danych strukturalnych OLX. Pokrycie metrażem: {cov}% bazy.</p>
</div>
""", """chBrackets('c1');renderBracketTable('t1');renderDistrictTable('t2',12);""",
'Elegancki raport/whitepaper: typografia szeryfowa, narracja + tabele. Do druku / udostępniania.')

# ============================================================================
# 05 — Sidebar Navigator
# ============================================================================
add('05-sidebar.html','05 · Sidebar Navigator', """
body{font-family:'Inter',system-ui,sans-serif;background:#f4f5fb;color:#1e293b;--accent:#6366f1}
.ribbon{position:fixed;top:0;right:0;background:#6366f1;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.layout{display:flex;min-height:100vh}
.side{width:230px;background:#1e1b4b;color:#c7d2fe;padding:24px 0;position:sticky;top:0;height:100vh}
.side h1{color:#fff;font-size:18px;padding:0 22px 20px}
.side a{display:block;padding:12px 22px;color:#c7d2fe;text-decoration:none;font-size:14px;border-left:3px solid transparent}
.side a:hover,.side a.active{background:rgba(255,255,255,.08);border-left-color:#818cf8;color:#fff}
.main{flex:1;padding:28px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:22px}
.kpi{background:#fff;border-radius:12px;padding:18px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.kpi h3{font-size:12px;color:#64748b;text-transform:uppercase}.kpi .v{font-size:28px;font-weight:800;color:#6366f1;margin-top:4px}
section{background:#fff;border-radius:12px;padding:22px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);scroll-margin-top:20px}
section h2{font-size:18px;margin-bottom:14px}
.cw{height:320px;position:relative}
""", f"""
{RIBBON(5,'Sidebar Navigator')}
<div class="layout">
 <nav class="side"><h1>📐 zł/m² Lublin</h1>
  <a href="#przeglad" class="active">Przegląd</a><a href="#przedzialy">Przedziały metrażu</a>
  <a href="#dzielnice">Dzielnice</a><a href="#heat">Mapa cieplna</a><a href="#scatter">Korelacja</a>
  <a href="../index.html">← Mapa ofert</a></nav>
 <div class="main">
  <div class="kpis">
   <div class="kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
   <div class="kpi"><h3>Mediana ceny</h3><div class="v">{mp:,}</div></div>
   <div class="kpi"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
   <div class="kpi"><h3>Ofert</h3><div class="v">{n}</div></div>
  </div>
  <section id="przeglad"><h2>Rozkład zł/m²</h2><div class="cw"><canvas id="c3"></canvas></div></section>
  <section id="przedzialy"><h2>Cena za m² wg przedziału</h2><div class="cw"><canvas id="c1"></canvas></div></section>
  <section id="dzielnice"><h2>Dzielnice</h2><div class="cw"><canvas id="c5"></canvas></div></section>
  <section id="heat"><h2>Mapa cieplna dzielnica × metraż</h2><div id="hm"></div></section>
  <section id="scatter"><h2>Powierzchnia vs cena</h2><div class="cw"><canvas id="c4"></canvas></div></section>
 </div>
</div>
""", """chPpmHist('c3');chBrackets('c1');chDistricts('c5','median_ppm');renderHeatmap('hm');chScatter('c4');
document.querySelectorAll('.side a[href^="#"]').forEach(a=>a.onclick=()=>{document.querySelectorAll('.side a').forEach(x=>x.classList.remove('active'));a.classList.add('active');});""",
'Aplikacja z lewym menu nawigacyjnym i sekcjami przewijanymi — wrażenie pełnego narzędzia SaaS.')

# ============================================================================
# 06 — Tabbed Explorer
# ============================================================================
add('06-tabbed.html','06 · Tabbed Explorer', """
body{font-family:system-ui,sans-serif;background:#eef2f7;color:#0f172a;padding:20px;--accent:#0ea5e9}
.ribbon{position:fixed;top:0;right:0;background:#0ea5e9;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1200px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 6px 30px rgba(0,0,0,.08)}
.head{background:linear-gradient(120deg,#0ea5e9,#2563eb);color:#fff;padding:26px 28px}
.head h1{font-size:24px}.head p{opacity:.9;margin-top:4px}
.tabs{display:flex;gap:4px;padding:0 28px;background:#f8fafc;border-bottom:1px solid #e2e8f0;flex-wrap:wrap}
.tab{padding:14px 18px;cursor:pointer;font-weight:600;color:#64748b;border-bottom:3px solid transparent}
.tab.active{color:#0ea5e9;border-bottom-color:#0ea5e9}
.pane{display:none;padding:28px}.pane.active{display:block}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:20px}
.kpi{background:#f1f5f9;border-radius:10px;padding:16px}.kpi h3{font-size:12px;color:#64748b}.kpi .v{font-size:26px;font-weight:800;color:#0ea5e9}
.cw{height:340px;position:relative}
""", f"""
{RIBBON(6,'Tabbed Explorer')}
<div class="container">
 <div class="head"><h1>📐 Analiza cen wg metrażu — Lublin</h1><p>{n} ofert · mediana {ppm} zł/m²</p></div>
 <div class="tabs">
  <div class="tab active" data-t="p1">Przegląd</div><div class="tab" data-t="p2">Przedziały</div>
  <div class="tab" data-t="p3">Dzielnice</div><div class="tab" data-t="p4">Korelacja</div><div class="tab" data-t="p5">Pokoje</div>
 </div>
 <div class="pane active" id="p1">
  <div class="kpis"><div class="kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
   <div class="kpi"><h3>Mediana ceny</h3><div class="v">{mp:,}</div></div>
   <div class="kpi"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
   <div class="kpi"><h3>Widełki</h3><div class="v" style="font-size:20px">{O['p25_ppm']}–{O['p75_ppm']}</div></div></div>
  <div class="cw"><canvas id="c3"></canvas></div></div>
 <div class="pane" id="p2"><div class="cw"><canvas id="c1"></canvas></div><div id="t1" style="margin-top:20px"></div></div>
 <div class="pane" id="p3"><div class="cw"><canvas id="c5"></canvas></div></div>
 <div class="pane" id="p4"><div class="cw"><canvas id="c4"></canvas></div></div>
 <div class="pane" id="p5"><div class="cw"><canvas id="c6"></canvas></div></div>
</div>
""", """chPpmHist('c3');chBrackets('c1');renderBracketTable('t1');chDistricts('c5','median_ppm');chScatter('c4');chRooms('c6');
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab,.pane').forEach(x=>x.classList.remove('active'));t.classList.add('active');el(t.dataset.t).classList.add('active');});""",
'Zakładki: Przegląd / Przedziały / Dzielnice / Korelacja / Pokoje — porządkuje dużo treści w kompaktowej karcie.')

# ============================================================================
# 07 — Heatmapa-centric
# ============================================================================
add('07-heatmapa.html','07 · Heatmapa', """
body{font-family:system-ui,sans-serif;background:#fbfbfd;color:#1c1c28;padding:24px;--accent:#e11d48}
.ribbon{position:fixed;top:0;right:0;background:#e11d48;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1200px;margin:0 auto}
h1{font-size:26px;margin-bottom:4px}.sub{color:#6b7280;margin-bottom:24px}
.hero{background:#fff;border-radius:16px;padding:26px;box-shadow:0 4px 20px rgba(0,0,0,.06);margin-bottom:22px}
.hero h2{font-size:20px;margin-bottom:6px}.hero p{color:#6b7280;margin-bottom:18px;font-size:14px}
table.hm td{padding:14px 8px;font-size:14px}
table.hm th{font-size:12px;padding:8px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.panel{background:#fff;border-radius:16px;padding:22px;box-shadow:0 4px 20px rgba(0,0,0,.06)}
.panel h2{font-size:16px;margin-bottom:14px}
.cw{height:300px;position:relative}
.legend{display:flex;align-items:center;gap:8px;font-size:12px;color:#6b7280;margin-top:14px}
.legbar{height:12px;width:160px;border-radius:6px;background:linear-gradient(90deg,rgb(40,180,120),rgb(240,30,40))}
.back-link{color:#e11d48;text-decoration:none;font-size:14px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(7,'Heatmapa')}
<div class="container">
 <a class="back-link" href="../index.html">← powrót</a>
 <h1>🔥 Mapa cieplna cen</h1><div class="sub">Mediana zł/m² w przecięciu dzielnica × przedział metrażu</div>
 <div class="hero"><h2>Gdzie metr jest najdroższy?</h2>
  <p>Wartości w zł/m². Zielony = tanio, czerwony = drogo. Im mniejszy metraż, tym wyższa stawka.</p>
  <div id="hm"></div>
  <div class="legend"><span>tanio</span><div class="legbar"></div><span>drogo</span></div></div>
 <div class="grid">
  <div class="panel"><h2>Średnia zł/m² wg metrażu</h2><div class="cw"><canvas id="c1"></canvas></div></div>
  <div class="panel"><h2>Dzielnice wg zł/m²</h2><div class="cw"><canvas id="c5"></canvas></div></div>
 </div>
</div>
""", """renderHeatmap('hm');chBrackets('c1');chDistricts('c5','median_ppm',10);""",
'Heatmapa dzielnica×metraż jako bohater strony — natychmiast widać gdzie metr jest najdroższy.')

# ============================================================================
# 08 — Kalkulator-first
# ============================================================================
add('08-kalkulator.html','08 · Kalkulator', """
body{font-family:system-ui,sans-serif;background:linear-gradient(160deg,#0f766e,#134e4a);min-height:100vh;color:#fff;padding:24px;--accent:#14b8a6}
.ribbon{position:fixed;top:0;right:0;background:#14b8a6;color:#063;font-weight:700;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:900px;margin:0 auto}
h1{font-size:28px;text-align:center;margin-bottom:6px}.sub{text-align:center;opacity:.85;margin-bottom:26px}
.calc{background:#fff;color:#134e4a;border-radius:20px;padding:34px;box-shadow:0 20px 50px rgba(0,0,0,.25);margin-bottom:24px}
.calc label{display:block;font-weight:700;margin:14px 0 6px;font-size:14px}
.calc input,.calc select{width:100%;padding:14px;font-size:18px;border:2px solid #99f6e4;border-radius:12px;outline:none}
.calc input:focus,.calc select:focus{border-color:#14b8a6}
.result{margin-top:26px;text-align:center;background:#f0fdfa;border-radius:16px;padding:24px}
.result .big{font-size:52px;font-weight:900;color:#0f766e}
.result .ppm{font-size:16px;color:#0d9488;margin-top:4px}
.note{font-size:13px;color:#5e7d78;margin-top:14px}
.panel{background:rgba(255,255,255,.12);backdrop-filter:blur(8px);border-radius:16px;padding:22px}
.panel h2{font-size:16px;margin-bottom:14px}.cw{height:280px;position:relative}
.back-link{display:block;text-align:center;color:#fff;margin-top:20px;text-decoration:underline}
""", f"""
{RIBBON(8,'Kalkulator')}
<div class="container">
 <h1>💸 Ile powinno kosztować Twoje mieszkanie?</h1>
 <div class="sub">Wpisz metraż i dzielnicę — oszacujemy czynsz na podstawie {n} ofert</div>
 <div class="calc">
  <label>Powierzchnia (m²)</label><input id="area" type="number" value="{ar:.0f}" min="10" max="200">
  <label>Dzielnica</label><select id="dist"></select>
  <div class="result"><div>Szacowany czynsz najmu:</div><div class="big" id="out">—</div>
   <div class="ppm">stawka: <span id="ppm">—</span></div>
   <div class="note">Mediana rynkowa. Połowa ofert mieści się w widełkach {O['p25_ppm']}–{O['p75_ppm']} zł/m².</div></div>
 </div>
 <div class="panel"><h2>📊 Stawka zł/m² wg metrażu (na czym opieramy szacunek)</h2><div class="cw"><canvas id="c1"></canvas></div></div>
 <a class="back-link" href="../index.html">← powrót do mapy ofert</a>
</div>
""", """Chart.defaults.color='#fff';initCalc('area','dist','out','ppm');chBrackets('c1');""",
'Interaktywny kalkulator "wpisz metraż → szacowany czynsz" jako główny punkt. Praktyczne narzędzie dla użytkownika.')

# ============================================================================
# 09 — Magazyn / Editorial
# ============================================================================
add('09-magazyn.html','09 · Magazyn', """
body{font-family:'Georgia',serif;background:#fff;color:#111;--accent:#c0392b}
.ribbon{position:fixed;top:0;right:0;background:#c0392b;color:#fff;font-size:11px;padding:5px 12px;font-family:sans-serif;z-index:99}
.cover{background:#111;color:#fff;padding:60px 24px;text-align:center}
.cover .kicker{color:#e74c3c;letter-spacing:.3em;text-transform:uppercase;font-family:sans-serif;font-size:13px;margin-bottom:14px}
.cover h1{font-size:48px;max-width:760px;margin:0 auto;line-height:1.15}
.cover .by{font-family:sans-serif;opacity:.7;margin-top:18px;font-size:14px}
.wrap{max-width:900px;margin:0 auto;padding:40px 24px}
.dropcap::first-letter{font-size:62px;float:left;line-height:.8;padding:6px 10px 0 0;color:#c0392b;font-weight:bold}
.lead{font-size:20px;line-height:1.7}
.pull{font-size:30px;line-height:1.3;color:#c0392b;border-left:5px solid #c0392b;padding-left:20px;margin:30px 0;font-style:italic}
.statrow{display:flex;gap:30px;justify-content:center;text-align:center;margin:34px 0;font-family:sans-serif;flex-wrap:wrap}
.statrow .v{font-size:40px;font-weight:800;color:#111}.statrow small{color:#888;display:block}
.cw{height:320px;position:relative;font-family:sans-serif;margin:24px 0}
h2{font-size:28px;margin:34px 0 12px}
.back-link{font-family:sans-serif;color:#c0392b}
""", f"""
{RIBBON(9,'Magazyn')}
<div class="cover"><div class="kicker">Raport rynkowy · Lublin {M['last_scan'][:7]}</div>
 <h1>Mały metraż, wielka cena za metr</h1>
 <div class="by">SONAR MIESZKANIOWY · na podstawie {n} ogłoszeń najmu</div></div>
<div class="wrap">
 <a class="back-link" href="../index.html">← powrót</a>
 <p class="lead dropcap">Rynek najmu w Lublinie rządzi się prostą zasadą: im mniejsze mieszkanie, tym drożej płacisz za każdy metr.
 Mediana stawki to dziś <b>{ppm} zł/m²</b>, ale dla kawalerek potrafi przekroczyć {S['area_brackets'][0]['median_ppm']:.0f} zł.</p>
 <div class="statrow"><div><div class="v">{mp:,} zł</div><small>mediana czynszu</small></div>
  <div><div class="v">{ppm}</div><small>zł za m²</small></div>
  <div><div class="v">{ar} m²</div><small>typowy metraż</small></div></div>
 <p class="pull">„Kawalerka kosztuje za metr nawet dwa razy więcej niż mieszkanie 70-metrowe."</p>
 <div class="cw"><canvas id="c1"></canvas></div>
 <h2>Dzielnice nie są równe</h2>
 <p class="lead">Najdroższy metr znajdziesz na Starym Mieście i Węglinie, najtańszy — na dużych osiedlach z wielkiej płyty.</p>
 <div class="cw"><canvas id="c5"></canvas></div>
</div>
""", """chBrackets('c1');chDistricts('c5','median_ppm',10);""",
'Format magazynowo-reporterski: okładka, dropcap, pull-quote, duże liczby. Storytelling wokół danych.')

# ============================================================================
# 10 — Mobilny (phone-first)
# ============================================================================
add('10-mobilny.html','10 · Mobilny', """
body{font-family:system-ui,sans-serif;background:#f0f2f5;padding:14px;--accent:#7c3aed}
.ribbon{position:fixed;top:0;right:0;background:#7c3aed;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.phone{max-width:420px;margin:0 auto;background:#fff;border-radius:26px;overflow:hidden;box-shadow:0 16px 50px rgba(0,0,0,.18)}
.top{background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;padding:24px 20px 28px}
.top h1{font-size:20px}.top p{opacity:.9;font-size:13px;margin-top:4px}
.hero{background:rgba(255,255,255,.18);border-radius:14px;padding:16px;margin-top:16px;text-align:center}
.hero .v{font-size:38px;font-weight:800}.hero small{opacity:.9}
.body{padding:16px}
.chips{display:flex;gap:8px;overflow-x:auto;padding-bottom:8px;margin-bottom:8px}
.chip{background:#f3e8ff;color:#7c3aed;border-radius:20px;padding:8px 14px;font-size:13px;font-weight:600;white-space:nowrap}
.card{background:#fff;border:1px solid #eee;border-radius:14px;padding:16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.card h2{font-size:15px;margin-bottom:12px}.cw{height:230px;position:relative}
.list .row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f0f0f0;font-size:14px}
.list .row b{color:#7c3aed}
.back-link{display:block;text-align:center;color:#7c3aed;padding:14px;text-decoration:none}
""", f"""
{RIBBON(10,'Mobilny')}
<div class="phone">
 <div class="top"><h1>📐 Ceny wg metrażu</h1><p>Lublin · {n} ofert</p>
  <div class="hero"><small>mediana stawki</small><div class="v">{ppm} zł/m²</div><small>{mp:,} zł · {ar} m²</small></div></div>
 <div class="body">
  <div class="chips"><div class="chip">Przedziały</div><div class="chip">Dzielnice</div><div class="chip">Pokoje</div><div class="chip">Rozkład</div></div>
  <div class="card"><h2>Cena za m² wg metrażu</h2><div class="cw"><canvas id="c1"></canvas></div></div>
  <div class="card"><h2>Czynsz wg liczby pokoi</h2><div class="cw"><canvas id="c6"></canvas></div></div>
  <div class="card"><h2>Dzielnice (zł/m²)</h2><div class="list" id="dl"></div></div>
 </div>
 <a class="back-link" href="../index.html">← powrót do mapy</a>
</div>
""", """chBrackets('c1');chRooms('c6');
const dl=el('dl');dl.innerHTML=S.districts.slice(0,8).map(d=>`<div class="row"><span>${d.name}</span><b>${PPM(d.median_ppm)}</b></div>`).join('');""",
'Widok mobilny (ramka telefonu): chipsy filtrów, karty, lista dzielnic. Pokazuje jak strona wygląda na komórce.')

# ============================================================================
# 11 — Neumorphism
# ============================================================================
add('11-neumorphism.html','11 · Neumorphism', """
body{font-family:'Poppins',system-ui,sans-serif;background:#e0e5ec;color:#3d4659;padding:26px;--accent:#5a67d8}
.ribbon{position:fixed;top:0;right:0;background:#5a67d8;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1200px;margin:0 auto}
h1{font-size:26px;margin-bottom:22px;text-align:center}
.soft{background:#e0e5ec;border-radius:20px;box-shadow:9px 9px 18px #b8bdc4,-9px -9px 18px #ffffff}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:22px;margin-bottom:24px}
.kpi{padding:22px;text-align:center}.kpi h3{font-size:12px;color:#8a93a6;text-transform:uppercase}.kpi .v{font-size:30px;font-weight:800;color:#5a67d8;margin-top:6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.panel{padding:24px;margin-bottom:24px}.panel h2{font-size:17px;margin-bottom:16px}.cw{height:300px;position:relative}
.back-link{display:inline-block;padding:10px 22px;border-radius:14px;text-decoration:none;color:#5a67d8;font-weight:600}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(11,'Neumorphism')}
<div class="container">
 <h1>📐 Analiza cen wg metrażu — Lublin</h1>
 <div class="kpis">
  <div class="soft kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
  <div class="soft kpi"><h3>Mediana ceny</h3><div class="v">{mp:,}</div></div>
  <div class="soft kpi"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
  <div class="soft kpi"><h3>Ofert</h3><div class="v">{n}</div></div>
 </div>
 <div class="soft panel"><h2>Cena za m² wg przedziału metrażu</h2><div class="cw"><canvas id="c1"></canvas></div></div>
 <div class="grid">
  <div class="soft panel"><h2>Rozkład zł/m²</h2><div class="cw"><canvas id="c3"></canvas></div></div>
  <div class="soft panel"><h2>Dzielnice</h2><div class="cw"><canvas id="c5"></canvas></div></div>
 </div>
 <div style="text-align:center"><a class="soft back-link" href="../index.html">← powrót do mapy</a></div>
</div>
""", """chBrackets('c1');chPpmHist('c3');chDistricts('c5','median_ppm',10);""",
'Miękkie UI (neumorfizm) — wytłaczane karty, delikatna paleta. Nowoczesny, spokojny wygląd.')

# ============================================================================
# 12 — TV / Kiosk (fullscreen)
# ============================================================================
add('12-kiosk.html','12 · TV / Kiosk', """
body{font-family:'Inter',system-ui,sans-serif;background:#06070d;color:#fff;height:100vh;overflow:hidden;--accent:#22d3ee}
.ribbon{position:fixed;top:0;right:0;background:#22d3ee;color:#06070d;font-weight:700;font-size:11px;padding:5px 12px;z-index:99}
.screen{height:100vh;padding:30px;display:grid;grid-template-rows:auto 1fr;gap:20px}
.bar{display:flex;justify-content:space-between;align-items:center}
.bar h1{font-size:30px;color:#22d3ee}.bar .clock{font-size:16px;color:#64748b}
.grid{display:grid;grid-template-columns:1.4fr 1fr 1fr;grid-template-rows:1fr 1fr;gap:18px}
.tile{background:#0f1729;border:1px solid #1e293b;border-radius:16px;padding:20px;display:flex;flex-direction:column}
.tile h2{font-size:14px;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.tile.big{grid-row:span 2}
.cw{flex:1;position:relative;min-height:0}
.mega{font-size:64px;font-weight:900;color:#22d3ee;line-height:1}
.mega small{font-size:16px;color:#94a3b8;display:block;margin-top:8px}
.statline{display:flex;justify-content:space-between;font-size:22px;padding:8px 0;border-bottom:1px solid #1e293b}
.statline b{color:#22d3ee}
""", f"""
{RIBBON(12,'TV / Kiosk')}
<div class="screen">
 <div class="bar"><h1>📐 RYNEK NAJMU LUBLIN · zł/m²</h1><div class="clock" id="clk"></div></div>
 <div class="grid">
  <div class="tile big"><h2>Cena za m² wg metrażu</h2><div class="cw"><canvas id="c1"></canvas></div></div>
  <div class="tile"><h2>Mediana stawki</h2><div class="mega">{ppm}<small>zł/m² · {n} ofert</small></div></div>
  <div class="tile"><h2>Kluczowe liczby</h2>
   <div class="statline"><span>Mediana ceny</span><b>{mp:,} zł</b></div>
   <div class="statline"><span>Mediana m²</span><b>{ar} m²</b></div>
   <div class="statline"><span>Widełki zł/m²</span><b>{O['p25_ppm']}–{O['p75_ppm']}</b></div></div>
  <div class="tile"><h2>Dzielnice (zł/m²)</h2><div class="cw"><canvas id="c5"></canvas></div></div>
  <div class="tile"><h2>Rozkład zł/m²</h2><div class="cw"><canvas id="c3"></canvas></div></div>
 </div>
</div>
""", """Chart.defaults.color='#94a3b8';chBrackets('c1');chDistricts('c5','median_ppm',8);chPpmHist('c3');
function tick(){el('clk').textContent=new Date().toLocaleString('pl-PL');}tick();setInterval(tick,1000);""",
'Pełnoekranowy kokpit "na ścianę/TV": kafelki, mega-liczby, zegar. Do wyświetlania na monitorze.')

# ============================================================================
# 13 — Porównywarka dzielnic
# ============================================================================
add('13-porownywarka.html','13 · Porównywarka', """
body{font-family:system-ui,sans-serif;background:#f8fafc;color:#0f172a;padding:24px;--accent:#2563eb}
.ribbon{position:fixed;top:0;right:0;background:#2563eb;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1100px;margin:0 auto}
h1{font-size:26px;margin-bottom:4px}.sub{color:#64748b;margin-bottom:22px}
.pick{display:flex;gap:16px;margin-bottom:22px;flex-wrap:wrap}
.pick select{flex:1;min-width:220px;padding:14px;font-size:16px;border:2px solid #cbd5e1;border-radius:12px}
.vs{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.col{background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 10px rgba(0,0,0,.06);border-top:5px solid #2563eb}
.col.b{border-top-color:#f59e0b}
.col h2{font-size:22px;margin-bottom:16px}
.metric{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #f1f5f9}
.metric .v{font-weight:800;font-size:18px}
.panel{background:#fff;border-radius:16px;padding:22px;margin-top:20px;box-shadow:0 2px 10px rgba(0,0,0,.06)}
.cw{height:300px;position:relative}
.back-link{color:#2563eb;text-decoration:none;font-size:14px}
@media(max-width:760px){.vs{grid-template-columns:1fr}}
""", f"""
{RIBBON(13,'Porównywarka')}
<div class="container">
 <a class="back-link" href="../index.html">← powrót</a>
 <h1>⚖️ Porównaj dzielnice</h1><div class="sub">Wybierz dwie dzielnice i zestaw stawki najmu</div>
 <div class="pick"><select id="dA"></select><select id="dB"></select></div>
 <div class="vs">
  <div class="col" id="colA"></div>
  <div class="col b" id="colB"></div>
 </div>
 <div class="panel"><h2 style="font-size:16px;margin-bottom:14px">Wszystkie dzielnice — zł/m²</h2><div class="cw"><canvas id="c5"></canvas></div></div>
</div>
""", """const D=S.districts;
function fill(s,i){s.innerHTML=D.map((d,j)=>`<option value="${j}" ${j===i?'selected':''}>${d.name}</option>`).join('');}
fill(el('dA'),0);fill(el('dB'),Math.min(5,D.length-1));
function card(id,j){const d=D[j];el(id).innerHTML=`<h2>${d.name}</h2>
 <div class="metric"><span>Mediana zł/m²</span><span class="v">${PPM(d.median_ppm)}</span></div>
 <div class="metric"><span>Mediana czynszu</span><span class="v">${PLN(d.median_price)}</span></div>
 <div class="metric"><span>Typowy metraż</span><span class="v">${d.median_area} m²</span></div>
 <div class="metric"><span>Liczba ofert</span><span class="v">${d.count}</span></div>`;}
function upd(){card('colA',+el('dA').value);card('colB',+el('dB').value);}
el('dA').onchange=upd;el('dB').onchange=upd;upd();chDistricts('c5','median_ppm');""",
'Porównywarka 1:1 dwóch dzielnic + ranking. Dobre dla kogoś, kto wybiera gdzie szukać mieszkania.')

# ============================================================================
# 14 — Scatter hero (korelacja)
# ============================================================================
add('14-scatter.html','14 · Korelacja', """
body{font-family:system-ui,sans-serif;background:#111827;color:#e5e7eb;padding:24px;--accent:#34d399}
.ribbon{position:fixed;top:0;right:0;background:#34d399;color:#064e3b;font-weight:700;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1200px;margin:0 auto}
h1{font-size:26px;margin-bottom:4px;color:#34d399}.sub{color:#9ca3af;margin-bottom:22px}
.hero{background:#1f2937;border-radius:16px;padding:24px;margin-bottom:20px}
.hero .cw{height:460px;position:relative}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.kpi{background:#1f2937;border-radius:14px;padding:20px}.kpi h3{font-size:12px;color:#9ca3af;text-transform:uppercase}.kpi .v{font-size:30px;font-weight:800;color:#34d399;margin-top:6px}
.panel{background:#1f2937;border-radius:16px;padding:22px;margin-top:20px}.panel h2{font-size:16px;margin-bottom:14px}.cw{height:300px;position:relative}
.back-link{color:#34d399;text-decoration:none;font-size:14px}
""", f"""
{RIBBON(14,'Korelacja')}
<div class="container">
 <a class="back-link" href="../index.html">← powrót</a>
 <h1>📈 Powierzchnia ↔ cena</h1><div class="sub">Każdy punkt to jedna oferta · próbka {len(S['scatter'])} z {n}</div>
 <div class="hero"><div class="cw"><canvas id="c4"></canvas></div></div>
 <div class="grid">
  <div class="kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
  <div class="kpi"><h3>Mediana ceny</h3><div class="v">{mp:,}</div></div>
  <div class="kpi"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
  <div class="kpi"><h3>Rozpiętość zł/m²</h3><div class="v" style="font-size:22px">{O['min_ppm']:.0f}–{O['max_ppm']:.0f}</div></div>
 </div>
 <div class="panel"><h2>Spadek zł/m² wraz z metrażem</h2><div class="cw"><canvas id="c1"></canvas></div></div>
</div>
""", """Chart.defaults.color='#9ca3af';Chart.defaults.borderColor='rgba(255,255,255,.08)';chScatter('c4');chBrackets('c1');""",
'Wykres rozrzutu powierzchnia×cena jako bohater (ciemny). Pokazuje surową korelację na poziomie pojedynczych ofert.')

# ============================================================================
# 15 — Karty przedziałów (każdy przedział = duża kafelka)
# ============================================================================
br_cards = "".join(
 f'<div class="bcard" style="--c:{c}"><div class="lab">{b["label"]}</div>'
 f'<div class="ppm">{b["median_ppm"]:.0f}<span>zł/m²</span></div>'
 f'<div class="meta">mediana {b["median_price"]:,} zł · {b["count"]} ofert</div>'
 f'<div class="rng">widełki {b["p25_price"]:,}–{b["p75_price"]:,} zł</div></div>'
 for b,c in zip(S['area_brackets'],
   ['#10b981','#22c55e','#84cc16','#eab308','#f97316','#ef4444','#dc2626']))
add('15-karty-przedzialy.html','15 · Karty przedziałów', """
body{font-family:system-ui,sans-serif;background:#f1f5f9;color:#0f172a;padding:24px;--accent:#0d9488}
.ribbon{position:fixed;top:0;right:0;background:#0d9488;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1200px;margin:0 auto}
h1{font-size:26px;margin-bottom:4px}.sub{color:#64748b;margin-bottom:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-bottom:24px}
.bcard{background:#fff;border-radius:16px;padding:22px;box-shadow:0 2px 10px rgba(0,0,0,.06);border-left:6px solid var(--c)}
.bcard .lab{font-size:14px;color:#64748b;font-weight:600}
.bcard .ppm{font-size:40px;font-weight:900;color:var(--c);margin:6px 0}.bcard .ppm span{font-size:15px;color:#94a3b8;font-weight:600}
.bcard .meta{font-size:13px;color:#475569}.bcard .rng{font-size:12px;color:#94a3b8;margin-top:6px}
.panel{background:#fff;border-radius:16px;padding:22px;box-shadow:0 2px 10px rgba(0,0,0,.06)}
.panel h2{font-size:17px;margin-bottom:14px}.cw{height:320px;position:relative}
.back-link{color:#0d9488;text-decoration:none;font-size:14px}
""", f"""
{RIBBON(15,'Karty przedziałów')}
<div class="container">
 <a class="back-link" href="../index.html">← powrót</a>
 <h1>🧱 Przedziały metrażu</h1><div class="sub">Mediana stawki najmu w każdym przedziale powierzchni · {n} ofert</div>
 <div class="cards">{br_cards}</div>
 <div class="panel"><h2>Cena za m² maleje z metrażem</h2><div class="cw"><canvas id="c1"></canvas></div></div>
</div>
""", """chBrackets('c1');""",
'Każdy przedział metrażu jako duża, kolorowa kafelka z kluczową liczbą. Bardzo czytelne "ile za metr".')

# ============================================================================
# 16 — Trend / Prognoza (buduje informacje na przyszłość)
# ============================================================================
add('16-trend-prognoza.html','16 · Trend / Prognoza', """
body{font-family:system-ui,sans-serif;background:#fafafa;color:#18181b;padding:24px;--accent:#8b5cf6}
.ribbon{position:fixed;top:0;right:0;background:#8b5cf6;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1100px;margin:0 auto}
h1{font-size:26px;margin-bottom:4px}.sub{color:#71717a;margin-bottom:22px}
.banner{background:linear-gradient(120deg,#8b5cf6,#6366f1);color:#fff;border-radius:16px;padding:22px 26px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px}
.banner .v{font-size:34px;font-weight:800}.banner small{opacity:.85}
.panel{background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 10px rgba(0,0,0,.05);margin-bottom:20px}
.panel h2{font-size:17px;margin-bottom:6px}.panel p{color:#71717a;font-size:14px;margin-bottom:14px}
.cw{height:330px;position:relative}
.note{background:#f5f3ff;border-left:4px solid #8b5cf6;padding:14px 18px;border-radius:8px;font-size:14px;color:#4c1d95}
.back-link{color:#8b5cf6;text-decoration:none;font-size:14px}
""", f"""
{RIBBON(16,'Trend / Prognoza')}
<div class="container">
 <a class="back-link" href="../index.html">← powrót</a>
 <h1>📅 Trend stawek w czasie</h1><div class="sub">Każdy skan dokłada dane — analiza buduje obraz rynku na przyszłość</div>
 <div class="banner"><div><small>Bieżąca mediana</small><div class="v">{ppm} zł/m²</div></div>
  <div><small>Obserwacje</small><div class="v">{len(S['trend'])} mies.</div></div>
  <div><small>Próbka łącznie</small><div class="v">{n}</div></div></div>
 <div class="panel"><h2>Mediana zł/m² i czynszu — miesiąc do miesiąca</h2>
  <p>Na podstawie daty pierwszego pojawienia się oferty (first_seen).</p>
  <div class="cw"><canvas id="ct"></canvas></div>
  <div class="note">📈 Wraz z kolejnymi skanami szereg czasowy wydłuża się, umożliwiając wykrywanie sezonowości i prognozowanie.</div></div>
 <div class="panel"><h2>Cena za m² wg metrażu (stan obecny)</h2><div class="cw"><canvas id="c1"></canvas></div></div>
</div>
""", """chTrend('ct');chBrackets('c1');""",
'Nacisk na szereg czasowy: mediana zł/m² miesiąc do miesiąca + komunikat o budowaniu danych na przyszłość.')

# ============================================================================
# 17 — Hybryda korporacyjna (heatmapa + tabele, niebieski)
# ============================================================================
add('17-korpo.html','17 · Korporacyjny', """
body{font-family:'Segoe UI',system-ui,sans-serif;background:#eef1f5;color:#1f2933;padding:0;--accent:#0b5394}
.ribbon{position:fixed;top:0;right:0;background:#0b5394;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.topbar{background:#0b5394;color:#fff;padding:18px 28px;display:flex;justify-content:space-between;align-items:center}
.topbar h1{font-size:20px}.topbar a{color:#cfe2ff;text-decoration:none;font-size:14px}
.container{max-width:1280px;margin:0 auto;padding:24px 28px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1px;background:#d6dee8;border-radius:8px;overflow:hidden;margin-bottom:22px}
.kpi{background:#fff;padding:20px}.kpi h3{font-size:12px;color:#627d98;text-transform:uppercase}.kpi .v{font-size:28px;font-weight:700;color:#0b5394;margin-top:6px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.panel{background:#fff;border:1px solid #d6dee8;border-radius:8px;padding:20px;margin-bottom:20px}
.panel h2{font-size:15px;color:#0b5394;border-bottom:2px solid #0b5394;padding-bottom:8px;margin-bottom:14px}
.cw{height:300px;position:relative}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(17,'Korporacyjny')}
<div class="topbar"><h1>SONAR MIESZKANIOWY · Analiza zł/m²</h1><a href="../index.html">← Mapa ofert</a></div>
<div class="container">
 <div class="kpis">
  <div class="kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
  <div class="kpi"><h3>Mediana czynszu</h3><div class="v">{mp:,}</div></div>
  <div class="kpi"><h3>Mediana metrażu</h3><div class="v">{ar} m²</div></div>
  <div class="kpi"><h3>Próbka</h3><div class="v">{n}</div></div>
  <div class="kpi"><h3>Pokrycie</h3><div class="v">{cov}%</div></div>
 </div>
 <div class="panel"><h2>Mapa cieplna: dzielnica × przedział metrażu (mediana zł/m²)</h2><div id="hm"></div></div>
 <div class="grid">
  <div class="panel"><h2>Cena za m² wg przedziału</h2><div class="cw"><canvas id="c1"></canvas></div></div>
  <div class="panel"><h2>Liczba ofert wg przedziału</h2><div class="cw"><canvas id="c2"></canvas></div></div>
 </div>
 <div class="grid">
  <div class="panel"><h2>Przedziały — zestawienie</h2><div id="t1"></div></div>
  <div class="panel"><h2>Dzielnice — zestawienie</h2><div id="t2"></div></div>
 </div>
</div>
""", """renderHeatmap('hm');chBrackets('c1');chBracketsCount('c2');renderBracketTable('t1');renderDistrictTable('t2',12);""",
'Stonowany, korporacyjny BI: górny pasek, siatka KPI, heatmapa + komplet tabel. Solidny, "biznesowy".')

# ============================================================================
# 18 — Pastel / friendly
# ============================================================================
add('18-pastel.html','18 · Pastel', """
body{font-family:'Quicksand','Nunito',system-ui,sans-serif;background:#fff5f7;color:#5b5b6b;padding:24px;--accent:#ec4899}
.ribbon{position:fixed;top:0;right:0;background:#ec4899;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1100px;margin:0 auto}
h1{font-size:28px;color:#db2777;margin-bottom:4px}.sub{margin-bottom:22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:18px;margin-bottom:24px}
.kpi{border-radius:22px;padding:22px;text-align:center}.kpi h3{font-size:13px;opacity:.7}.kpi .v{font-size:32px;font-weight:800;margin-top:6px}
.k1{background:#ffe4ef;color:#db2777}.k2{background:#e0f2fe;color:#0284c7}.k3{background:#dcfce7;color:#16a34a}.k4{background:#fef9c3;color:#ca8a04}
.panel{background:#fff;border-radius:22px;padding:24px;box-shadow:0 6px 24px rgba(236,72,153,.08);margin-bottom:20px}
.panel h2{font-size:18px;color:#db2777;margin-bottom:14px}.cw{height:300px;position:relative}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.back-link{color:#db2777;text-decoration:none;font-weight:700}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(18,'Pastel')}
<div class="container">
 <a class="back-link" href="../index.html">← powrót</a>
 <h1>📐 Ceny mieszkań wg metrażu 🏡</h1><div class="sub">Lublin · {n} ofert najmu · łatwo i przyjemnie</div>
 <div class="kpis">
  <div class="kpi k1"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
  <div class="kpi k2"><h3>Mediana ceny</h3><div class="v">{mp:,}</div></div>
  <div class="kpi k3"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
  <div class="kpi k4"><h3>Pokrycie</h3><div class="v">{cov}%</div></div>
 </div>
 <div class="panel"><h2>💗 Cena za metr wg wielkości mieszkania</h2><div class="cw"><canvas id="c1"></canvas></div></div>
 <div class="grid">
  <div class="panel"><h2>🍩 Udział przedziałów</h2><div class="cw"><canvas id="c2"></canvas></div></div>
  <div class="panel"><h2>🏙️ Dzielnice</h2><div class="cw"><canvas id="c5"></canvas></div></div>
 </div>
</div>
""", """chBrackets('c1');chDoughnutBrackets('c2');chDistricts('c5','median_ppm',10);""",
'Lekki, przyjazny, pastelowy — zaokrąglenia, emoji, miękkie kolory. Dla szerokiego, niefachowego odbiorcy.')

# ============================================================================
# 19 — Terminal / data-geek
# ============================================================================
add('19-terminal.html','19 · Terminal', """
body{font-family:'JetBrains Mono','Courier New',monospace;background:#0a0e0a;color:#33ff66;padding:24px;--accent:#33ff66}
.ribbon{position:fixed;top:0;right:0;background:#33ff66;color:#0a0e0a;font-weight:700;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1100px;margin:0 auto}
.term{border:1px solid #1f3a1f;border-radius:8px;padding:18px;margin-bottom:18px;background:#0d140d}
.prompt{color:#7fff9f}.prompt::before{content:"$ ";color:#4a8a5a}
h1{font-size:20px;margin-bottom:14px;color:#7fff9f}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:18px}
.kpi{border:1px solid #1f3a1f;padding:14px;border-radius:6px}.kpi h3{font-size:11px;color:#4a8a5a}.kpi .v{font-size:26px;font-weight:700;margin-top:4px}
.panel{border:1px solid #1f3a1f;border-radius:8px;padding:18px;margin-bottom:18px;background:#0d140d}
.panel h2{font-size:14px;color:#7fff9f;margin-bottom:12px}.cw{height:300px;position:relative}
table.tbl th,table.tbl td{border-bottom:1px solid #1f3a1f}table.tbl tr:hover td{background:rgba(51,255,102,.06)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.back-link{color:#7fff9f}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
""", f"""
{RIBBON(19,'Terminal')}
<div class="container">
 <div class="term"><div class="prompt">sonar analyze --metric=zl_per_m2 --city=lublin</div>
  <div style="color:#9fdfaf;margin-top:8px">loaded {M['total_offers']} offers · {n} with area ({cov}%) · last_scan={M['last_scan'][:16]}</div></div>
 <h1>// ROZKŁAD CENY ZA METR</h1>
 <div class="kpis">
  <div class="kpi"><h3>median_zl_m2</h3><div class="v">{ppm}</div></div>
  <div class="kpi"><h3>median_price</h3><div class="v">{mp:,}</div></div>
  <div class="kpi"><h3>median_area</h3><div class="v">{ar}</div></div>
  <div class="kpi"><h3>p25..p75</h3><div class="v" style="font-size:18px">{O['p25_ppm']}..{O['p75_ppm']}</div></div>
  <div class="kpi"><h3>n</h3><div class="v">{n}</div></div>
 </div>
 <div class="grid">
  <div class="panel"><h2>brackets[zl_m2]</h2><div class="cw"><canvas id="c1"></canvas></div></div>
  <div class="panel"><h2>histogram[zl_m2]</h2><div class="cw"><canvas id="c3"></canvas></div></div>
 </div>
 <div class="panel"><h2>table: brackets</h2><div id="t1"></div></div>
 <a class="back-link" href="../index.html">&lt;- back to map</a>
</div>
""", """Chart.defaults.color='#4a8a5a';Chart.defaults.borderColor='rgba(51,255,102,.12)';chBrackets('c1');chPpmHist('c3');renderBracketTable('t1');""",
'Estetyka terminala/CLI dla geeków danych — monospace, zielony fosfor, "surowe" nazwy metryk.')

# ============================================================================
# 20 — All-in-one Mega Dashboard (wszystkie wykresy)
# ============================================================================
add('20-mega.html','20 · Mega Dashboard', """
body{font-family:system-ui,sans-serif;background:#f5f6fa;color:#1a1d29;padding:20px;--accent:#4f46e5}
.ribbon{position:fixed;top:0;right:0;background:#4f46e5;color:#fff;font-size:11px;padding:5px 12px;z-index:99}
.container{max-width:1500px;margin:0 auto}
header{background:linear-gradient(120deg,#4f46e5,#7c3aed);color:#fff;border-radius:16px;padding:24px 28px;margin-bottom:18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
header h1{font-size:24px}header a{color:#e0e7ff;text-decoration:none}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.kpi{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.07)}
.kpi h3{font-size:11px;color:#6b7280;text-transform:uppercase}.kpi .v{font-size:24px;font-weight:800;color:#4f46e5;margin-top:4px}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}
.panel{background:#fff;border-radius:12px;padding:18px;box-shadow:0 1px 3px rgba(0,0,0,.07)}
.panel h2{font-size:14px;margin-bottom:12px;color:#374151}
.cw{height:260px;position:relative}
.s4{grid-column:span 4}.s6{grid-column:span 6}.s8{grid-column:span 8}.s12{grid-column:span 12}
@media(max-width:1000px){.s4,.s6,.s8{grid-column:span 12}}
""", f"""
{RIBBON(20,'Mega Dashboard')}
<div class="container">
 <header><h1>📐 Centrum analizy cen wg metrażu — Lublin</h1><a href="../index.html">← Mapa ofert</a></header>
 <div class="kpis">
  <div class="kpi"><h3>Mediana zł/m²</h3><div class="v">{ppm}</div></div>
  <div class="kpi"><h3>Mediana ceny</h3><div class="v">{mp:,}</div></div>
  <div class="kpi"><h3>Mediana m²</h3><div class="v">{ar}</div></div>
  <div class="kpi"><h3>Ofert</h3><div class="v">{n}</div></div>
  <div class="kpi"><h3>Widełki zł/m²</h3><div class="v" style="font-size:17px">{O['p25_ppm']}–{O['p75_ppm']}</div></div>
  <div class="kpi"><h3>Pokrycie</h3><div class="v">{cov}%</div></div>
 </div>
 <div class="grid">
  <div class="panel s8"><h2>Cena za m² wg przedziału metrażu</h2><div class="cw"><canvas id="c1"></canvas></div></div>
  <div class="panel s4"><h2>Udział przedziałów</h2><div class="cw"><canvas id="c2"></canvas></div></div>
  <div class="panel s4"><h2>Rozkład zł/m²</h2><div class="cw"><canvas id="c3"></canvas></div></div>
  <div class="panel s8"><h2>Powierzchnia vs cena</h2><div class="cw"><canvas id="c4"></canvas></div></div>
  <div class="panel s6"><h2>Dzielnice — zł/m²</h2><div class="cw"><canvas id="c5"></canvas></div></div>
  <div class="panel s6"><h2>Czynsz wg liczby pokoi</h2><div class="cw"><canvas id="c6"></canvas></div></div>
  <div class="panel s8"><h2>Mapa cieplna dzielnica × metraż</h2><div id="hm"></div></div>
  <div class="panel s4"><h2>Trend zł/m²</h2><div class="cw"><canvas id="ct"></canvas></div></div>
  <div class="panel s6"><h2>Tabela przedziałów</h2><div id="t1"></div></div>
  <div class="panel s6"><h2>Tabela dzielnic</h2><div id="t2"></div></div>
 </div>
</div>
""", """chBrackets('c1');chDoughnutBrackets('c2');chPpmHist('c3');chScatter('c4');chDistricts('c5','median_ppm',10);chRooms('c6');renderHeatmap('hm');chTrend('ct');renderBracketTable('t1');renderDistrictTable('t2',12);""",
'Maksymalny kokpit: wszystkie wykresy i tabele na jednej siatce 12-kolumnowej. "Wszystko na raz".')

# ============================================================================
# INDEX galerii
# ============================================================================
cards = "".join(
 f'''<div class="card">
  <div class="frame"><iframe src="{m['file']}" loading="lazy"></iframe></div>
  <div class="info"><h3><a href="{m['file']}" target="_blank">{m['title']}</a></h3>
   <p>{m['note']}</p>
   <a class="open" href="{m['file']}" target="_blank">Otwórz pełny widok →</a></div>
 </div>''' for m in MOCKUPS)

index = f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mockupy — Analiza cen wg metrażu</title>
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:28px}}
.wrap{{max-width:1500px;margin:0 auto}}
h1{{font-size:30px;margin-bottom:6px}}
.lead{{color:#94a3b8;margin-bottom:8px;max-width:820px;line-height:1.6}}
.meta{{color:#64748b;font-size:13px;margin-bottom:26px}}
.meta b{{color:#a5b4fc}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:22px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:14px;overflow:hidden;display:flex;flex-direction:column}}
.frame{{height:300px;overflow:hidden;border-bottom:1px solid #334155;background:#fff;position:relative}}
.frame iframe{{width:1400px;height:1000px;border:0;transform:scale(.30);transform-origin:top left;pointer-events:none}}
.info{{padding:16px}}
.info h3{{font-size:17px;margin-bottom:6px}}
.info h3 a{{color:#e2e8f0;text-decoration:none}}
.info p{{color:#94a3b8;font-size:13px;line-height:1.5;margin-bottom:10px;min-height:54px}}
.open{{color:#818cf8;text-decoration:none;font-weight:600;font-size:14px}}
.back{{color:#818cf8;text-decoration:none}}
.note{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px 20px;margin:24px 0;font-size:14px;color:#cbd5e1;line-height:1.6}}
</style></head>
<body><div class="wrap">
 <a class="back" href="../index.html">← powrót do serwisu</a>
 <h1 style="margin-top:14px">📐 Analiza cen wg metrażu — 20 mockupów</h1>
 <p class="lead">Propozycje nowej podstrony analizującej treść ogłoszeń: cena za m², przedziały metrażu,
 podział na dzielnice, mapy cieplne, trendy i kalkulator. Wybierz koncepcję, którą rozwiniemy do produkcji.</p>
 <div class="meta">Dane realne z <b>data/offers.json</b>: przeanalizowano <b>{M['analyzed']}</b> z {M['total_offers']} ofert
 (metraż wykryty w <b>{M['coverage_pct']}%</b>) · mediana <b>{O['median_ppm']} zł/m²</b> · ostatni skan {M['last_scan'][:16].replace('T',' ')}.</p>
 <div class="note">💡 Miniatury to żywe, pomniejszone strony (iframe). Kliknij „Otwórz pełny widok", aby zobaczyć interaktywny mockup z działającymi wykresami i filtrami.
 Wszystkie 20 korzysta z tego samego zbioru danych — różnią się układem, stylem i doborem wizualizacji.</div>
 <div class="grid">{cards}</div>
</div></body></html>"""
(HERE / 'index.html').write_text(index, encoding='utf-8')
print(f"Wygenerowano {len(MOCKUPS)} mockupów + index.html w {HERE}")
for m in MOCKUPS: print(' -', m['file'])
