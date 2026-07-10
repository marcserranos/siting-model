"""Stage 8: baxtel datacenter sites from their public Mapbox tileset (ericbell.baxtel_sites).
The tileset is served with the public token embedded in baxtel.com's page for every visitor;
fields per feature: site_name, company_name, company_type, category, layer_stage,
primary_stage, status, public_id, region_slug. Fetches z8 tiles over Spain, decodes PBF.
Their internal /api/sites endpoint is 401 (not public) and is NOT touched."""
import json, math, os, time
import requests
import mapbox_vector_tile

TOKEN = "pk.eyJ1IjoiZXJpY2JlbGwiLCJhIjoiY2swcHB1ZWh3MDBkZDNtbXFjdHVpdWo3cCJ9.L0X1OXz8U_D4fD1hHeViwg"
Z = 8
LON0, LON1, LAT0, LAT1 = -9.6, 4.5, 35.8, 44.0
CACHE = "data/baxtel_tiles"
os.makedirs(CACHE, exist_ok=True)

def tile_of(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y

x0, y1 = tile_of(LON0, LAT0, Z)  # y grows north->south
x1, y0 = tile_of(LON1, LAT1, Z)
print(f"z{Z} tiles x{x0}-{x1} y{y0}-{y1} = {(x1-x0+1)*(y1-y0+1)}")

S = requests.Session()
sites = {}
for x in range(x0, x1 + 1):
    for y in range(y0, y1 + 1):
        path = f"{CACHE}/{Z}_{x}_{y}.pbf"
        if os.path.exists(path):
            buf = open(path, "rb").read()
        else:
            r = S.get(f"https://a.tiles.mapbox.com/v4/ericbell.baxtel_sites/{Z}/{x}/{y}.vector.pbf",
                      params={"access_token": TOKEN}, timeout=30)
            if r.status_code == 404:  # empty tile
                open(path, "wb").write(b""); continue
            r.raise_for_status()
            buf = r.content
            open(path, "wb").write(buf)
            time.sleep(0.05)
        if not buf: continue
        tile = mapbox_vector_tile.decode(buf)
        layer = tile.get("baxtel_sites")
        if not layer: continue
        extent = layer.get("extent", 4096)
        n = 2 ** Z
        for f in layer["features"]:
            p = f["properties"]
            gx, gy = f["geometry"]["coordinates"] if f["geometry"]["type"] == "Point" else (None, None)
            if gx is None: continue
            # mapbox_vector_tile flips y to origin bottom-left
            lon = (x + gx / extent) / n * 360 - 180
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1 - gy / extent) / n))))
            sites[p.get("public_id") or f'{lon:.4f},{lat:.4f}'] = {
                "name": p.get("site_name"), "company": p.get("company_name"),
                "stage": p.get("primary_stage"), "layer_stage": p.get("layer_stage"),
                "status": p.get("status"), "category": p.get("category"),
                "ctype": p.get("company_type"), "region": p.get("region_slug"),
                "lat": round(lat, 5), "lon": round(lon, 5),
            }
print("sites decoded:", len(sites))
json.dump(list(sites.values()), open("data/baxtel_sites.json", "w"), ensure_ascii=False, indent=0)
from collections import Counter
print("stages:", Counter(s["stage"] for s in sites.values()))
print("regions:", Counter(s["region"] for s in sites.values()).most_common(8))
