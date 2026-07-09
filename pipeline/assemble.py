"""Stage 5: join all layers -> web/data/cells.json (compact arrays for client-side scoring)."""
import csv, json, math

# Cities >~100k pop (approx coords; suburbs of Madrid/Barcelona folded into the metro point).
CITIES = [
    ("Madrid", 40.42, -3.70, 3300), ("Barcelona", 41.39, 2.16, 1660), ("Valencia", 39.47, -0.38, 800),
    ("Sevilla", 37.39, -5.99, 690), ("Zaragoza", 41.65, -0.88, 680), ("Málaga", 36.72, -4.42, 580),
    ("Murcia", 37.99, -1.13, 460), ("Palma", 39.57, 2.65, 420), ("Bilbao", 43.26, -2.93, 350),
    ("Alicante", 38.35, -0.48, 340), ("Córdoba", 37.89, -4.78, 325), ("Valladolid", 41.65, -4.72, 300),
    ("Vigo", 42.24, -8.72, 295), ("Gijón", 43.54, -5.66, 270), ("A Coruña", 43.36, -8.41, 245),
    ("Vitoria-Gasteiz", 42.85, -2.67, 250), ("Granada", 37.18, -3.60, 230), ("Elche", 38.27, -0.70, 230),
    ("Oviedo", 43.36, -5.85, 220), ("Cartagena", 37.61, -0.99, 215), ("Jerez", 36.68, -6.14, 210),
    ("Pamplona", 42.82, -1.65, 200), ("Almería", 36.84, -2.46, 200), ("Donostia", 43.32, -1.98, 185),
    ("Burgos", 42.34, -3.70, 175), ("Santander", 43.46, -3.80, 170), ("Castellón", 39.99, -0.04, 170),
    ("Albacete", 38.99, -1.86, 170), ("Logroño", 42.47, -2.45, 150), ("Badajoz", 38.88, -6.97, 150),
    ("Salamanca", 40.97, -5.66, 145), ("Huelva", 37.26, -6.94, 145), ("Lleida", 41.62, 0.62, 140),
    ("Marbella", 36.51, -4.88, 150), ("Tarragona", 41.12, 1.25, 135), ("León", 42.60, -5.57, 125),
    ("Cádiz", 36.53, -6.29, 115), ("Jaén", 37.77, -3.79, 110), ("Ourense", 42.34, -7.86, 105),
    ("Girona", 41.98, 2.82, 105), ("Lugo", 43.01, -7.56, 100), ("Cáceres", 39.48, -6.37, 95),
    ("Toledo", 39.86, -4.02, 85), ("Talavera de la Reina", 39.96, -4.83, 84),
]
# Announced/operating DC sites from this session's research (see PROGRESS.md / regions.json).
DCS = [
    ("Madrid colo ring", 40.45, -3.62, "Operating national colo hub (Alcobendas–San Blas–Getafe)"),
    ("Barcelona colo", 41.39, 2.16, "Operating colo market"),
    ("AWS Región Aragón", 41.55, -0.72, "El Burgo de Ebro / Villanueva de Gállego / Huesca; PIGA expansion, ~30 buildings planned"),
    ("AWS Huesca", 42.14, -0.41, "AWS Aragón region AZ"),
    ("Microsoft La Muela", 41.58, -1.19, "Región MSFT PIGA campus"),
    ("Microsoft Villamayor de Gállego", 41.69, -0.77, "Región MSFT PIGA campus"),
    ("Meta Talavera", 39.96, -4.83, "Hyperscale campus under construction; national water-controversy reference case"),
    ("Merlin Edged Navalmoral", 39.90, -5.54, "PREMIA, €1.6B, up to 1 GW IT"),
    ("Merlin Edged Valdecaballeros", 39.24, -5.19, "Announced twin campus, up to 1 GW IT"),
    ("Merlin Arasur (Álava)", 42.73, -2.87, "Operating/expanding, Ribera Baja"),
    ("A Coruña DC", 43.36, -8.41, "Announced project"),
    ("Picassent DC", 39.36, -0.46, "Announced project (Valencia)"),
]

def hav(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2-lat1)*p)/2 + math.cos(lat1*p)*math.cos(lat2*p)*(1-math.cos((lon2-lon1)*p))/2
    return 12742 * math.asin(math.sqrt(a))

grid = {r["id"]: r for r in csv.DictReader(open("data/grid.csv"))}
pv = {r[0]: r for r in csv.reader(open("data/pvgis.csv"))}
elev = {r[0]: r for r in csv.reader(open("data/elev.csv"))}
isa = {r["id"]: r for r in csv.DictReader(open("data/isa.csv"))}
isa2 = {r["id"]: r for r in csv.DictReader(open("data/isa2.csv"))}
power = {r["id"]: r for r in csv.DictReader(open("data/power.csv"))}
pv_mw = {}  # existing OSM-mapped solar capacity per cell
try:
    for la, lo, mw, _ in json.load(open("data/solar_farms.json")):
        k = (round(math.floor(la/0.1)*0.1+0.05, 3), round(math.floor(lo/0.1)*0.1+0.05, 3))
        pv_mw[k] = pv_mw.get(k, 0) + mw
except FileNotFoundError:
    pass

cells, skipped = [], 0
for cid, g in grid.items():
    p, e, s = pv.get(cid), elev.get(cid), isa.get(cid)
    if not p or not p[1] or not s:
        skipped += 1
        continue
    lat, lon = float(g["lat"]), float(g["lon"])
    dc_j = min(range(len(DCS)), key=lambda j: hav(lat, lon, DCS[j][1], DCS[j][2]))
    big = [j for j, c in enumerate(CITIES) if c[3] >= 100]
    ci_j = min(big, key=lambda j: hav(lat, lon, CITIES[j][1], CITIES[j][2]))
    relief = int(e[2]) if e else -1
    cells.append([
        lat, lon, g["ccaa"], round(float(p[1])),                      # 0-3 lat lon ccaa yield
        round(float(p[2])) if p[2] else 0, relief,                    # 4-5 elev relief(-1 = pending)
        float(s["f_valid"]), float(s["f_maxima"]), float(s["f_muyalta"]),
        float(s["f_alta"]), float(s["f_moderada"]), float(s["f_baja"]),  # 6-11 ISA fractions
        round(hav(lat, lon, CITIES[ci_j][1], CITIES[ci_j][2])), ci_j,    # 12-13 d_city km, idx
        round(hav(lat, lon, DCS[dc_j][1], DCS[dc_j][2])), dc_j,          # 14-15 d_dc km, idx
        float(isa2[cid]["isa_val"] or 0), float(isa2[cid]["eol_val"] or 0),  # 16-17 continuous ISA pv/wind
        float(isa2[cid]["eol_dev"] or 0), int(isa2[cid]["patch_ha"]),        # 18-19 wind dev frac, patch ha
        float(power[cid]["ws50"]), int(power[cid]["precip_mm_yr"]),          # 20-21 wind m/s, precip mm/yr
        round(pv_mw.get((lat, lon), 0)),                                     # 22 existing PV MW in cell (OSM)
    ])

out = {
    "meta": {
        "built": "2026-07-06", "step_deg": 0.1,
        "fields": ["lat","lon","ccaa","pv_yield_kwh_kwp","elev_m","relief_m","f_valid",
                   "f_maxima","f_muyalta","f_alta","f_moderada","f_baja","d_city_km","city_idx","d_dc_km","dc_idx",
                   "isa_val_pv","isa_val_eol","eol_dev_frac","patch_ha","ws50_ms","precip_mm_yr","existing_pv_mw"],
        "cell_area_km2_approx": 94, "isa_source": "MITECO Zonificación FTV 2023 (25m, sampled 200m)",
        "pv_source": "PVGIS v5.3 SARAH3, 1kWp fixed optimal tilt, 14% losses",
        "elev_source": "Open-Meteo / Copernicus GLO-90, 4x4 subgrid"
    },
    "cities": CITIES, "dcs": DCS, "cells": cells,
}
json.dump(out, open("web/data/cells.json", "w"), separators=(",", ":"))
print(f"{len(cells)} cells written, {skipped} skipped (no PVGIS/ISA), "
      f"{sum(1 for c in cells if c[5] < 0)} awaiting relief")
