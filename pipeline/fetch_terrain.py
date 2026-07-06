"""Stage 3 (v2): per-cell terrain relief from AWS Terrain Tiles (Terrarium encoding, ~300m at z9).
Replaces Open-Meteo approach (hourly quota too small). elevation = R*256 + G + B/256 - 32768."""
import csv, io, math, os
import numpy as np, requests
from PIL import Image

Z = 9
TILE_DIR = "data/terrain_tiles"
os.makedirs(TILE_DIR, exist_ok=True)
S = requests.Session()
cache = {}

def tile_arr(tx, ty):
    k = (tx, ty)
    if k in cache: return cache[k]
    path = f"{TILE_DIR}/{tx}_{ty}.png"
    if not os.path.exists(path):
        r = S.get(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{tx}/{ty}.png", timeout=30)
        r.raise_for_status()
        open(path, "wb").write(r.content)
    a = np.asarray(Image.open(path)).astype(np.float32)
    cache[k] = a[:,:,0]*256 + a[:,:,1] + a[:,:,2]/256 - 32768
    if len(cache) > 60: cache.pop(next(iter(cache)))
    return cache[k]

N = 256 * (2 ** Z)
def px(lat, lon):
    x = (lon + 180) / 360 * N
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1+s)/(1-s)) / (4*math.pi)) * N
    return x, y

def window(lat0, lat1, lon0, lon1):
    x0, y0 = px(lat1, lon0); x1, y1 = px(lat0, lon1)  # y grows south
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    vals = []
    for tx in range(x0//256, x1//256 + 1):
        for ty in range(y0//256, y1//256 + 1):
            a = tile_arr(tx, ty)
            r0 = max(0, y0-ty*256); r1 = min(256, y1-ty*256)
            c0 = max(0, x0-tx*256); c1 = min(256, x1-tx*256)
            if r1 > r0 and c1 > c0: vals.append(a[r0:r1, c0:c1].ravel())
    return np.concatenate(vals) if vals else np.array([0.])

cells = list(csv.DictReader(open("data/grid.csv")))
with open("data/elev.csv", "w", newline="") as f:
    w = csv.writer(f)
    for i, c in enumerate(cells):
        lat, lon = float(c["lat"]), float(c["lon"])
        v = window(lat-0.05, lat+0.05, lon-0.05, lon+0.05)
        v = v[v > -1000]
        land = v[v > 0.5] if (v > 0.5).any() else v  # crude sea mask for coastal cells
        w.writerow((c["id"], round(float(land.mean())), round(float(np.percentile(land, 98) - np.percentile(land, 2)))))
        if i % 500 == 0: print(i, flush=True)
print("done", len(cells))
