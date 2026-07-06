"""Stage 1: build 0.1-degree grid over peninsular Spain + Balearics, tag each cell with its CCAA."""
import json, csv
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.prepared import prep

EXCLUDE = {"05", "18", "19", "20"}  # Canarias, Ceuta, Melilla, Gibraltar
STEP = 0.1

def decode_topojson(path):
    t = json.load(open(path))
    sx, sy = t["transform"]["scale"]; tx, ty = t["transform"]["translate"]
    arcs = []
    for arc in t["arcs"]:
        pts, x, y = [], 0, 0
        for dx, dy in arc:
            x += dx; y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    def ring(arc_idxs):
        pts = []
        for i in arc_idxs:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts.extend(a if not pts else a[1:])
        return pts
    out = {}
    for g in t["objects"]["autonomous_regions"]["geometries"]:
        cid = g["id"]
        if cid in EXCLUDE: continue
        if g["type"] == "Polygon":
            polys = [g["arcs"]]
        else:
            polys = g["arcs"]
        shp = []
        for p in polys:
            rings = [ring(r) for r in p]
            if len(rings[0]) >= 4:
                shp.append(Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4]))
        out[cid] = MultiPolygon(shp).buffer(0)
    return out

ccaa = decode_topojson("data/ccaa_topo.json")
prepared = {cid: prep(geom) for cid, geom in ccaa.items()}
minx = min(g.bounds[0] for g in ccaa.values()); maxx = max(g.bounds[2] for g in ccaa.values())
miny = min(g.bounds[1] for g in ccaa.values()); maxy = max(g.bounds[3] for g in ccaa.values())
print("bounds", round(minx,2), round(miny,2), round(maxx,2), round(maxy,2))

rows, cid_counter = [], 0
lat = round(miny - miny % STEP, 1)
while lat <= maxy:
    lon = round(minx - minx % STEP - STEP, 1)
    while lon <= maxx:
        p = Point(lon + STEP / 2, lat + STEP / 2)
        for rid, pg in prepared.items():
            if pg.contains(p):
                rows.append((cid_counter, round(lat + STEP/2, 3), round(lon + STEP/2, 3), rid))
                cid_counter += 1
                break
        lon = round(lon + STEP, 1)
    lat = round(lat + STEP, 1)

with open("data/grid.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["id", "lat", "lon", "ccaa"]); w.writerows(rows)
print(len(rows), "land cells")
