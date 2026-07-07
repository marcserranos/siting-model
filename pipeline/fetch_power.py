"""Stage 3b: NASA POWER climatology (0.5 deg) — mean 50m wind speed + annual precipitation per cell."""
import csv, json, requests

S = requests.Session()
pts = {}  # (lat,lon) -> {param: ANN}
for p in ("WS50M", "PRECTOTCORR"):
    for lo0, lo1 in ((-10, -2.5), (-2.5, 4.5)):
        r = S.get("https://power.larc.nasa.gov/api/temporal/climatology/regional",
                  params={"parameters": p, "community": "RE", "format": "JSON",
                          "latitude-min": 35.5, "latitude-max": 44, "longitude-min": lo0, "longitude-max": lo1},
                  timeout=180)
        r.raise_for_status()
        for f in r.json()["features"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            pts.setdefault((lat, lon), {})[p] = f["properties"]["parameter"][p]["ANN"]
        print(p, lo0, len(pts), flush=True)

keys = list(pts)
with open("data/power.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["id", "ws50", "precip_mm_yr"])
    for c in csv.DictReader(open("data/grid.csv")):
        lat, lon = float(c["lat"]), float(c["lon"])
        k = min(keys, key=lambda k: (k[0]-lat)**2 + (k[1]-lon)**2)
        ws = pts[k].get("WS50M"); pr = pts[k].get("PRECTOTCORR")
        # PRECTOTCORR climatology ANN is mm/day -> mm/yr
        w.writerow([c["id"], ws if ws is not None else "", round(pr*365.25) if pr is not None else ""])
print("done")
