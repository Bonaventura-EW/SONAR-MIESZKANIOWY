#!/usr/bin/env python3
"""Agregacja statystyk cena/metraż/dzielnica z pełnej historii ofert.
Wejście: data/offers.json -> Wyjście: docs/mockups/stats.json (na potrzeby mockupów)."""
import json, re, statistics, collections, datetime, pathlib, math

ROOT = pathlib.Path(__file__).resolve().parents[2]
offers = json.load(open(ROOT/'data'/'offers.json'))['offers']
last_scan = json.load(open(ROOT/'data'/'offers.json')).get('last_scan')

AREA_RE = re.compile(r'(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:m\s?[²2]\b|metr(?:ów|y|a)?\s*kw|mkw|m\.kw)', re.IGNORECASE)
ROOM_RE = re.compile(r'(\d)\s*[- ]?\s*pok', re.IGNORECASE)
DISTRICTS = ["Śródmieście","Czuby","Wrotków","LSM","Rury","Czechów","Bronowice",
    "Kalinowszczyzna","Tatary","Dziesiąta","Węglin","Sławinek","Sławin","Felin",
    "Ponikwoda","Wieniawa","Kośminek","Stare Miasto","Konstantynów","Abramowice","Zemborzyce","Szerokie"]

def area_of(o):
    for m in AREA_RE.finditer(o.get('description') or ''):
        v=float(m.group(1).replace(',','.'))
        if 8<=v<=300: return v
    return None
def rooms_of(o):
    m=ROOM_RE.search(o.get('description') or '')
    if m:
        r=int(m.group(1))
        if 1<=r<=6: return r
    return None
def district_of(o):
    t=((o.get('description') or '')+' '+(o.get('address',{}).get('full') or '')).lower()
    for d in DISTRICTS:
        if d.lower() in t: return "LSM" if d=="LSM" else d
    return None

recs=[]
for o in offers:
    p=o.get('price',{}).get('current')
    a=area_of(o); 
    if not p or not a: continue
    recs.append(dict(price=p, area=a, ppm=p/a, rooms=rooms_of(o),
                     district=district_of(o), first_seen=o.get('first_seen')))

def pct(xs,q):
    xs=sorted(xs); k=(len(xs)-1)*q; f=math.floor(k); c=math.ceil(k)
    if f==c: return xs[int(k)]
    return xs[f]*(c-k)+xs[c]*(k-f)
def med(xs): return round(statistics.median(xs)) if xs else None

prices=[r['price'] for r in recs]; areas=[r['area'] for r in recs]; ppms=[r['ppm'] for r in recs]
overall=dict(count=len(recs), median_price=med(prices), median_area=round(statistics.median(areas),1),
    median_ppm=round(statistics.median(ppms),1), mean_ppm=round(statistics.mean(ppms),1),
    min_ppm=round(min(ppms),1), max_ppm=round(max(ppms),1),
    p25_ppm=round(pct(ppms,.25),1), p75_ppm=round(pct(ppms,.75),1),
    p10_price=round(pct(prices,.10)), p90_price=round(pct(prices,.90)))

# area brackets
BRK=[(0,25,'do 25 m²'),(25,35,'25–35 m²'),(35,45,'35–45 m²'),(45,55,'45–55 m²'),
     (55,70,'55–70 m²'),(70,90,'70–90 m²'),(90,999,'90 m²+')]
area_brackets=[]
for lo,hi,lab in BRK:
    g=[r for r in recs if lo<=r['area']<hi]
    if not g: continue
    gp=[r['price'] for r in g]; gm=[r['ppm'] for r in g]
    area_brackets.append(dict(label=lab,min=lo,max=hi,count=len(g),
        median_price=med(gp),median_ppm=round(statistics.median(gm),1),
        p25_price=round(pct(gp,.25)),p75_price=round(pct(gp,.75)),
        min_price=min(gp),max_price=max(gp)))

# ppm histogram
binw=10; mx=120
bins=list(range(0,mx+binw,binw))
counts=[0]*(len(bins))
for r in recs:
    idx=min(int(r['ppm']//binw),len(bins)-1); counts[idx]+=1
ppm_hist=dict(labels=[f"{b}-{b+binw}" for b in bins[:-1]]+[f"{bins[-1]}+"],counts=counts)

# scatter sample
import random; random.seed(7)
sc=random.sample(recs,min(500,len(recs)))
scatter=[[round(r['area'],1),r['price']] for r in sc]

# districts
dd=collections.defaultdict(list)
for r in recs:
    if r['district']: dd[r['district']].append(r)
districts=[]
for name,g in dd.items():
    if len(g)<5: continue
    districts.append(dict(name=name,count=len(g),median_price=med([r['price'] for r in g]),
        median_area=round(statistics.median([r['area'] for r in g]),1),
        median_ppm=round(statistics.median([r['ppm'] for r in g]),1)))
districts.sort(key=lambda x:-x['median_ppm'])

# district x bracket heatmap (median ppm)
top_d=[d['name'] for d in sorted(districts,key=lambda x:-x['count'])[:8]]
brk_labels=[b['label'] for b in area_brackets]
matrix=[]
for dn in top_d:
    row=[]
    for b in area_brackets:
        g=[r for r in dd[dn] if b['min']<=r['area']<b['max']]
        row.append(round(statistics.median([r['ppm'] for r in g]),1) if len(g)>=2 else None)
    matrix.append(row)

# monthly trend from first_seen
mt=collections.defaultdict(list)
for r in recs:
    fs=r.get('first_seen')
    if not fs: continue
    try: m=fs[:7]
    except: continue
    mt[m].append(r)
trend=[]
for m in sorted(mt):
    g=mt[m]
    trend.append(dict(month=m,count=len(g),median_price=med([r['price'] for r in g]),
        median_ppm=round(statistics.median([r['ppm'] for r in g]),1)))

# rooms
rr=collections.defaultdict(list)
for r in recs:
    if r['rooms']: rr[r['rooms']].append(r)
rooms=[dict(rooms=k,count=len(v),median_price=med([x['price'] for x in v]),
    median_area=round(statistics.median([x['area'] for x in v]),1),
    median_ppm=round(statistics.median([x['ppm'] for x in v]),1)) for k,v in sorted(rr.items())]

out=dict(meta=dict(generated=datetime.datetime.now().isoformat(timespec='seconds'),
    last_scan=last_scan, total_offers=len(offers), analyzed=len(recs),
    coverage_pct=round(100*len(recs)/len(offers))),
    overall=overall, area_brackets=area_brackets, ppm_hist=ppm_hist, scatter=scatter,
    districts=districts, heatmap=dict(districts=top_d,brackets=brk_labels,ppm=matrix),
    trend=trend, rooms=rooms)
json.dump(out,open(pathlib.Path(__file__).parent/'stats.json','w'),ensure_ascii=False,indent=1)
print(json.dumps({k:(v if k in('meta','overall') else f'<{len(v)} items>') for k,v in out.items()},ensure_ascii=False,indent=1))
print("\nBRACKETS:")
for b in area_brackets: print(f"  {b['label']:<10} n={b['count']:<4} med={b['median_price']} zł  {b['median_ppm']} zł/m²")
print("\nDISTRICTS (top by ppm):")
for d in districts[:12]: print(f"  {d['name']:<16} n={d['count']:<4} med={d['median_price']} zł  {d['median_ppm']} zł/m²  {d['median_area']} m²")
