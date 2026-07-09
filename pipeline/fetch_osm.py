"""Refetch OSM ground-truth inputs via Overpass (mirrors rotate; they rate-limit)."""
import sys, time, requests

Q_SOLAR = '''[out:json][timeout:90];
area["ISO3166-1"="ES"][admin_level=2]->.es;
(way["power"="plant"]["plant:source"="solar"](area.es);
 relation["power"="plant"]["plant:source"="solar"](area.es););
out center bb tags qt;'''
Q_DC = '''[out:json][timeout:80];
(nwr["telecom"~"data_cent"](35.9,-9.5,43.9,4.4);
 nwr["building"~"data_cent"](35.9,-9.5,43.9,4.4););
out center tags qt;'''
MIRRORS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.private.coffee/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter"]

def fetch(q, out):
    for attempt in range(6):
        srv = MIRRORS[attempt % len(MIRRORS)]
        try:
            r = requests.post(srv, data={"data": q}, timeout=150)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                open(out, "w").write(r.text); print("ok", out, "via", srv); return
        except Exception: pass
        time.sleep(45)
    sys.exit(f"failed: {out}")

fetch(Q_SOLAR, "data/osm_solar.json")
fetch(Q_DC, "data/osm_dc.json")
