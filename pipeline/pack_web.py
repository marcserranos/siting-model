"""Stage 7: wrap web/data/*.json into script files so index.html works from file:// (no server).
Re-run after any data change."""
import json

PACK = [("cells.json", "__CELLS"), ("regions.json", "__REGIONS"),
        ("solar_farms.json", "__FARMS"), ("datacenters.json", "__DCS"),
        ("substations.json", "__SUBS")]
for fn, var in PACK:
    data = json.load(open(f"web/data/{fn}"))
    with open(f"web/data/{fn.replace('.json', '.js')}", "w") as f:
        f.write(f"window.{var}=")
        json.dump(data, f, separators=(",", ":"))
        f.write(";")
    print("packed", fn, "->", var)
