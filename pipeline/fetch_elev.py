"""Stage 3: intra-cell terrain relief via Open-Meteo elevation API (Copernicus GLO-90).
4x4 subgrid per cell -> mean elevation + relief (max-min). Batches of 96 points (6 cells/call)."""
import csv, os, time, requests

OUT = "data/elev.csv"
done = set()
if os.path.exists(OUT):
    done = {r[0] for r in csv.reader(open(OUT))}
cells = [r for r in csv.DictReader(open("data/grid.csv")) if r["id"] not in done]
print(f"{len(cells)} to fetch ({len(done)} done)")

OFF = [-0.0375, -0.0125, 0.0125, 0.0375]  # 4x4 subgrid within a 0.1-degree cell
f = open(OUT, "a", newline="")
w = csv.writer(f)
S = requests.Session()

for i in range(0, len(cells), 6):
    batch = cells[i:i+6]
    lats, lons = [], []
    for c in batch:
        for dy in OFF:
            for dx in OFF:
                lats.append(round(float(c["lat"]) + dy, 4))
                lons.append(round(float(c["lon"]) + dx, 4))
    for attempt in range(5):
        try:
            r = S.get("https://api.open-meteo.com/v1/elevation",
                      params={"latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons))},
                      timeout=30)
            if r.status_code == 200:
                ev = r.json()["elevation"]
                for j, c in enumerate(batch):
                    vals = [v for v in ev[j*16:(j+1)*16] if v is not None]
                    if vals:
                        w.writerow((c["id"], round(sum(vals)/len(vals)), round(max(vals)-min(vals))))
                break
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    if (i // 6) % 100 == 0:
        f.flush(); print(i, flush=True)
    time.sleep(0.12)
f.close()
print("done")
