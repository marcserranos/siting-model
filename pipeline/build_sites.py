"""Stage 6: ground-truth site layers.
- data/osm_solar.json (Overpass: power=plant + plant:source=solar in ES) -> web/data/solar_farms.json
- curated datacenter list (this session's primary-source research) + data/osm_dc.json if present
  -> web/data/datacenters.json  (status: operating|construction|announced|land)
The DC file is deliberately hand-editable: datacentermap.com / baxtel.com expose no free API
(both rate-limit scrapers; their data is the product) — add entries from them manually.
Re-fetch OSM inputs with pipeline/fetch_osm.py."""
import json, math, re

def parse_mw(s):
    m = re.match(r"([\d.,]+)\s*(k|M|G)?W", (s or "").replace(",", "."))
    if not m: return None
    v = float(m.group(1)); u = m.group(2) or ""
    return v/1000 if u == "k" else v*1000 if u == "G" else v

# ---- solar farms ----
els = [e for e in json.load(open("data/osm_solar.json"))["elements"] if "bounds" in e]
farms, n_tag = [], 0
for e in els:
    b = e["bounds"]; lat = (b["minlat"]+b["maxlat"])/2; lon = (b["minlon"]+b["maxlon"])/2
    if lat < 35: continue  # peninsula + Balearics only
    t = e.get("tags", {})
    mw = parse_mw(t.get("plant:output:electricity"))
    if mw: n_tag += 1
    else:
        km2 = abs(b["maxlat"]-b["minlat"])*111 * abs(b["maxlon"]-b["minlon"])*111*math.cos(math.radians(lat))
        mw = min(500, round(km2*0.6*50, 1))  # 60% bbox fill, ~50 MWp/km2
    farms.append([round(lat,4), round(lon,4), round(mw,1), t.get("name","")[:40]])
json.dump(farms, open("web/data/solar_farms.json","w"), separators=(",",":"))
print(f"solar farms: {len(farms)} ({n_tag} capacity-tagged), {round(sum(f[2] for f in farms)/1000,1)} GW")

# ---- datacenters ----
CURATED = [  # name, lat, lon, status, note (sources: PROGRESS.md research log)
    ["Madrid colo ring", 40.45, -3.62, "operating", "National colo hub (Alcobendas-San Blas-Getafe)"],
    ["Barcelona colo", 41.39, 2.16, "operating", "Colo market"],
    ["AWS El Burgo de Ebro", 41.55, -0.72, "operating", "AWS Aragon region; PIGA expansion approved 2026, ~30 buildings planned"],
    ["AWS Villanueva de Gallego", 41.77, -0.82, "operating", "AWS Aragon region AZ"],
    ["AWS Huesca", 42.14, -0.41, "operating", "AWS Aragon region AZ"],
    ["Microsoft La Muela", 41.58, -1.19, "announced", "Region MSFT PIGA, initial approval"],
    ["Microsoft Villamayor de Gallego", 41.69, -0.77, "announced", "Region MSFT PIGA"],
    ["Microsoft Zaragoza", 41.63, -0.95, "announced", "Region MSFT PIGA, 3rd campus"],
    ["Meta Talavera de la Reina", 39.96, -4.83, "construction", "Hyperscale; national water-controversy reference case"],
    ["Merlin Edged Navalmoral", 39.90, -5.54, "announced", "PREMIA declared, EUR 1.6B, up to 1 GW IT"],
    ["Merlin Edged Valdecaballeros", 39.24, -5.19, "announced", "Twin campus, up to 1 GW IT"],
    ["Merlin Arasur (Alava)", 42.73, -2.87, "operating", "Operating/expanding"],
    ["A Coruna DC", 43.36, -8.41, "announced", "Announced project"],
    ["Picassent DC", 39.36, -0.46, "announced", "Announced (Valencia)"],
]
dcs = [dict(name=n, lat=la, lon=lo, status=s, note=nt, src="research") for n,la,lo,s,nt in CURATED]
try:
    osm = json.load(open("data/osm_dc.json"))["elements"]
    added = 0
    for e in osm:
        c = e.get("center") or ({"lat":e.get("lat"), "lon":e.get("lon")} if e.get("lat") else None)
        t = e.get("tags", {})
        name = t.get("name") or t.get("operator")
        if not c or not name or c["lat"] < 35: continue
        if any(abs(d["lat"]-c["lat"]) < 0.03 and abs(d["lon"]-c["lon"]) < 0.04 for d in dcs): continue
        dcs.append(dict(name=name[:50], lat=round(c["lat"],4), lon=round(c["lon"],4),
                        status="operating", note="OpenStreetMap-mapped facility", src="osm"))
        added += 1
    print("OSM DCs merged:", added)
except FileNotFoundError:
    print("no data/osm_dc.json — curated list only")
json.dump(dcs, open("web/data/datacenters.json","w"), indent=1)
print("datacenters:", len(dcs))
