"""Stage 4: per-cell composition of MITECO PV environmental sensitivity classes.
Reads the 25m national raster decimated to ~200m, histograms each cell's bbox.
Classes: 0 Maxima(excluded) 1 MuyAlta 2 Alta 3 Moderada 4 Baja; 65535 nodata (sea/non-ES)."""
import csv
import numpy as np
import rasterio
from rasterio.warp import transform as wtransform

DEC = 8  # 25m * 8 = 200m sampling
r = rasterio.open("data/zonificacion_ftv/Clas_ISA_ftv_pb.tiff")
arr = r.read(1, out_shape=(r.height // DEC, r.width // DEC))
T = r.transform
px, py = T.a * DEC, T.e * DEC  # 200, -200
x0, y0 = T.c, T.f
print("decimated", arr.shape)

cells = list(csv.DictReader(open("data/grid.csv")))
lons, lats = [], []
for c in cells:
    lat, lon = float(c["lat"]), float(c["lon"])
    lons += [lon - 0.05, lon + 0.05]
    lats += [lat + 0.05, lat - 0.05]  # NW, SE corners
xs, ys = wtransform("EPSG:4326", "EPSG:25830", lons, lats)

with open("data/isa.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "f_valid", "f_maxima", "f_muyalta", "f_alta", "f_moderada", "f_baja"])
    for i, c in enumerate(cells):
        c0 = max(0, int((xs[2*i] - x0) / px)); c1 = min(arr.shape[1], int((xs[2*i+1] - x0) / px) + 1)
        r0 = max(0, int((ys[2*i] - y0) / py)); r1 = min(arr.shape[0], int((ys[2*i+1] - y0) / py) + 1)
        win = arr[r0:r1, c0:c1]
        n = win.size
        if n == 0:
            w.writerow([c["id"], 0, 0, 0, 0, 0, 0]); continue
        counts = [int((win == v).sum()) for v in range(5)]
        valid = sum(counts)
        w.writerow([c["id"], round(valid / n, 3)] +
                   [round(cnt / valid, 3) if valid else 0 for cnt in counts])
print("done", len(cells))
