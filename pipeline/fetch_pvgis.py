"""Stage 2: fetch PVGIS v5.3 specific yield (kWh/kWp/yr, optimal fixed tilt) per cell. Resume-safe."""
import csv, os, time, requests
from concurrent.futures import ThreadPoolExecutor

OUT = "data/pvgis.csv"
done = set()
if os.path.exists(OUT):
    done = {r[0] for r in csv.reader(open(OUT))}
cells = [r for r in csv.DictReader(open("data/grid.csv")) if r["id"] not in done]
print(f"{len(cells)} to fetch ({len(done)} done)")

f = open(OUT, "a", newline="")
w = csv.writer(f)
S = requests.Session()

def fetch(c):
    url = (f"https://re.jrc.ec.europa.eu/api/v5_3/PVcalc?lat={c['lat']}&lon={c['lon']}"
           f"&peakpower=1&loss=14&optimalangles=1&outputformat=json")
    for attempt in range(4):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 200:
                j = r.json()
                t = j["outputs"]["totals"]["fixed"]
                return (c["id"], t["E_y"], j["inputs"]["location"]["elevation"],
                        j["inputs"]["mounting_system"]["fixed"]["slope"]["value"])
            if r.status_code == 429:
                time.sleep(2 + attempt)
                continue
            return (c["id"], "", "", "")  # sea point / no data
        except Exception:
            time.sleep(2 + attempt)
    return None

n = 0
with ThreadPoolExecutor(max_workers=8) as ex:
    for res in ex.map(fetch, cells):
        if res:
            w.writerow(res); n += 1
            if n % 250 == 0:
                f.flush(); print(n, flush=True)
f.close()
print("done", n)
