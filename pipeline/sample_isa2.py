"""Stage 4b: per-cell sampling of (a) continuous PV ISA value, (b) wind sensitivity classes,
(c) continuous wind ISA, (d) largest contiguous developable patch (national, 200m) touching each cell.
Continuous 'Modelo ISA' rasters: higher value = LESS sensitive (10 = lowest sensitivity)."""
import csv, glob
import numpy as np
import rasterio
from rasterio.warp import transform as wtransform
from scipy import ndimage

DEC = 8

def dec_read(pattern):
    path = glob.glob(pattern)[0]
    r = rasterio.open(path)
    a = r.read(1, out_shape=(r.height // DEC, r.width // DEC))
    print(path, a.shape, a.dtype, r.nodata)
    return r, a

r_c, cls = dec_read("data/zonificacion_ftv/Clas_ISA_ftv_pb.tiff")            # 0..4 classes
r_v, val = dec_read("data/Modelo_ISA_FTV_2023/*[pb]*.tif*")                  # continuous
r_ec, ecls = dec_read("data/Zonificacion_EOL_clasificada_2023/*[pb]*.tif*")  # wind classes
r_ev, eval_ = dec_read("data/Modelo_ISA_EOL_2023/*[pb]*.tif*")               # wind continuous

# national developable mask (PV Baja+Moderada) -> connected components -> patch areas (ha)
mask = (cls == 3) | (cls == 4)
lab, n = ndimage.label(mask)
sizes = ndimage.sum_labels(np.ones_like(lab, dtype=np.int32), lab, index=np.arange(1, n + 1))
print("patches:", n, "largest_ha:", int(sizes.max() * 4))  # 200m px = 4 ha

cells = list(csv.DictReader(open("data/grid.csv")))
lons, lats = [], []
for c in cells:
    la, lo = float(c["lat"]), float(c["lon"])
    lons += [lo - 0.05, lo + 0.05]; lats += [la + 0.05, la - 0.05]
xs, ys = wtransform("EPSG:4326", "EPSG:25830", lons, lats)

def win(rast, arr, i):
    T = rast.transform
    px, py, x0, y0 = T.a * DEC, T.e * DEC, T.c, T.f
    c0 = max(0, int((xs[2*i] - x0) / px)); c1 = min(arr.shape[1], int((xs[2*i+1] - x0) / px) + 1)
    r0 = max(0, int((ys[2*i] - y0) / py)); r1 = min(arr.shape[0], int((ys[2*i+1] - y0) / py) + 1)
    return arr[r0:r1, c0:c1]

def mean_valid(w, nodata, lo=-1e9, hi=1e9):
    v = w[(w != nodata) & (w >= lo) & (w <= hi)]
    return round(float(v.mean()), 2) if v.size else ""

with open("data/isa2.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "isa_val", "eol_val", "eol_dev", "patch_ha"])
    for i, c in enumerate(cells):
        wv = win(r_v, val, i)
        we = win(r_ev, eval_, i)
        wc = win(r_ec, ecls, i)
        vc = wc[wc != 65535]
        eol_dev = round(float(((vc == 3) | (vc == 4)).sum() / vc.size), 3) if vc.size else ""
        wl = win(r_c, lab, i)
        ids = np.unique(wl); ids = ids[ids > 0]
        patch = int(sizes[ids - 1].max() * 4) if ids.size else 0
        # continuous rasters store value*1000 (0..10000, higher = less sensitive)
        iv = mean_valid(wv, 65535, 0, 10000); ev = mean_valid(we, 65535, 0, 10000)
        w.writerow([c["id"], round(iv/1000, 2) if iv != "" else "",
                    round(ev/1000, 2) if ev != "" else "", eol_dev, patch])
        if i % 1000 == 0: print(i, flush=True)
print("done")
