/* Spain BYOP siting dashboard — all scoring client-side, recomputes live. */
"use strict";

const F = {LAT:0, LON:1, CCAA:2, EY:3, ELEV:4, RELIEF:5, FVALID:6, FMAX:7, FMUYALTA:8, FALTA:9, FMOD:10, FBAJA:11, DCITY:12, CITYI:13, DDC:14, DCI:15};
const CELL_HA = 9400;          // ~94 km2 per 0.1-deg cell
const PUE = 1.15, HA_PER_MWP = 2, SOLAR_SHARE = 0.9, BESS_MWH_PER_MW = 10;

const MODES = {
  gw:   {label:"1 GW campus", it:1000, note:"Hyperscale AI campus. Land need computed from each cell's own solar yield; requires aggregating neighboring cells (~30 km radius).",
         w:{solar:90, env:80, terrain:70, reg:85, city:-30, dc:20}, gates:{relief:300, dev:0.35}},
  mw100:{label:"100 MW", it:100, note:"Large single-site campus; fits inside one cell's developable land in most of the meseta.",
         w:{solar:80, env:70, terrain:60, reg:70, city:20, dc:30}, gates:{relief:350, dev:0.15}},
  edge: {label:"10 MW edge", it:10, note:"Regional/edge site; proximity to labor and fiber flips to a positive.",
         w:{solar:50, env:30, terrain:30, reg:40, city:80, dc:10}, gates:{relief:500, dev:0.05}},
};

const LAYERS = [
  {k:"solar", label:"Solar yield", dual:false,
   hint:"PVGIS specific yield, optimal fixed tilt",
   raw:c=>c[F.EY], fmt:c=>c[F.EY]+" kWh/kWp·yr",
   norm:c=>clamp((c[F.EY]-1250)/(1800-1250))},
  {k:"env", label:"Env. permitting", dual:false,
   hint:"MITECO sensitivity: share of cell in Baja/Moderada",
   raw:c=>devFrac(c), fmt:c=>Math.round(devFrac(c)*100)+"% developable",
   norm:c=>devFrac(c)},
  {k:"terrain", label:"Buildable terrain", dual:false,
   hint:"Intra-cell elevation range (lower = flatter)",
   raw:c=>c[F.RELIEF], fmt:c=>c[F.RELIEF]<0?"n/a":c[F.RELIEF]+" m relief",
   norm:c=>c[F.RELIEF]<0?0.5:1-clamp(c[F.RELIEF]/600)},
  {k:"reg", label:"Regulatory reception", dual:false,
   hint:"Per-region score from primary-source dossier",
   raw:c=>REGIONS[c[F.CCAA]].score, fmt:c=>REGIONS[c[F.CCAA]].score+"/100 · "+REGIONS[c[F.CCAA]].name,
   norm:c=>REGIONS[c[F.CCAA]].score/100},
  {k:"city", label:"City proximity", dual:true,
   hint:"Labor/fiber (+) vs pushback exposure (−); negative weight prefers remote",
   raw:c=>c[F.DCITY], fmt:c=>c[F.DCITY]+" km to "+DATA.cities[c[F.CITYI]][0],
   norm:c=>1-clamp(c[F.DCITY]/150)},
  {k:"dc", label:"DC cluster proximity", dual:true,
   hint:"Validated corridor (+) vs uncontested whitespace (−)",
   raw:c=>c[F.DDC], fmt:c=>c[F.DDC]+" km to "+DATA.dcs[c[F.DCI]][0],
   norm:c=>1-clamp(c[F.DDC]/250)},
];

const clamp = v => Math.max(0, Math.min(1, v));
const devFrac = c => (c[F.FMOD]+c[F.FBAJA]) * c[F.FVALID];
const devHa = c => devFrac(c) * CELL_HA;

let DATA, REGIONS, map, canvasLayer;
let state = {mode:"gw", w:{}, on:{}, gates:{}, view:"score"};
let scores = [], pass = [], clusterHa = [], byKey = new Map(), selected = -1;

// PV system sizing for a mode at a given cell's yield
function sizing(itMW, ey){
  const loadMW = itMW * PUE;
  const mwp = loadMW * 8760 * SOLAR_SHARE / ey;
  return {loadMW, mwp, bess: loadMW * BESS_MWH_PER_MW,
          ha: mwp * HA_PER_MWP + itMW * 0.03};
}

function computeScores(){
  const g = state.gates, m = MODES[state.mode];
  const needHa = sizing(m.it, 1750).ha; // gate on land using a reference yield; exact math shown per-cell
  pass = DATA.cells.map(c =>
    c[F.FVALID] >= 0.3 &&
    (c[F.RELIEF] < 0 || c[F.RELIEF] <= g.relief) &&
    devFrac(c) >= g.dev);
  // land availability: own cell + 8 neighbors that pass gates (GW mode needs aggregation)
  clusterHa = DATA.cells.map((c,i)=>{
    if(!pass[i]) return 0;
    let ha = devHa(c);
    for(const j of neighbors(i)) if(pass[j]) ha += devHa(DATA.cells[j]);
    return ha;
  });
  if(state.mode === "gw") pass = pass.map((p,i)=> p && clusterHa[i] >= needHa);
  else pass = pass.map((p,i)=> p && devHa(DATA.cells[i]) >= needHa);

  let sumW = 0; for(const L of LAYERS) if(state.on[L.k]) sumW += Math.abs(state.w[L.k]);
  scores = DATA.cells.map((c,i)=>{
    if(!pass[i] || !sumW) return -1;
    let s = 0;
    for(const L of LAYERS){
      if(!state.on[L.k]) continue;
      const w = state.w[L.k], n = L.norm(c);
      s += Math.abs(w) * (w >= 0 ? n : 1-n);
    }
    return 100 * s / sumW;
  });
}

function neighbors(i){
  const c = DATA.cells[i], out = [];
  for(let dy=-1; dy<=1; dy++) for(let dx=-1; dx<=1; dx++){
    if(!dx && !dy) continue;
    const j = byKey.get(key(c[F.LAT]+dy*0.1, c[F.LON]+dx*0.1));
    if(j !== undefined) out.push(j);
  }
  return out;
}
const key = (lat,lon) => Math.round(lat*100)+"_"+Math.round(lon*100);

// ---------- color ----------
function viridis(t){
  t = clamp(t);
  const st = [[44,26,77],[32,144,140],[122,209,81],[253,231,37]];
  const x = t*3, i = Math.min(2, Math.floor(x)), f = x-i;
  const a = st[i], b = st[i+1];
  return `rgb(${a.map((v,k)=>Math.round(v+(b[k]-v)*f)).join(",")})`;
}

// ---------- canvas cell layer ----------
const CellLayer = L.Layer.extend({
  onAdd(m){
    this._c = L.DomUtil.create("canvas", "", m.getPane("overlayPane"));
    this._ctx = this._c.getContext("2d");
    m.on("moveend zoomend resize", this.redraw, this);
    this.redraw();
  },
  redraw(){
    const m = map, size = m.getSize();
    const tl = m.containerPointToLayerPoint([0,0]);
    L.DomUtil.setPosition(this._c, tl);
    this._c.width = size.x; this._c.height = size.y;
    const ctx = this._ctx;
    const layerView = LAYERS.find(L2 => L2.k === state.view);
    for(let i=0; i<DATA.cells.length; i++){
      const c = DATA.cells[i];
      const p1 = m.latLngToContainerPoint([c[F.LAT]+0.05, c[F.LON]-0.05]);
      const p2 = m.latLngToContainerPoint([c[F.LAT]-0.05, c[F.LON]+0.05]);
      if(p2.x < 0 || p1.x > size.x || p2.y < 0 || p1.y > size.y) continue;
      let fill, alpha = 0.72;
      if(state.view === "score"){
        const s = scores[i];
        if(s === undefined || s < 0){ fill = "#3a3f4a"; alpha = 0.35; }
        else fill = viridis((s-35)/50);  // stretch: composite scores live in ~35-85
      } else {
        fill = viridis(layerView.norm(c)); alpha = 0.7;
      }
      ctx.globalAlpha = alpha; ctx.fillStyle = fill;
      ctx.fillRect(p1.x, p1.y, Math.max(1.2, p2.x-p1.x-0.4), Math.max(1.2, p2.y-p1.y-0.4));
      if(i === selected){
        ctx.globalAlpha = 1; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
        ctx.strokeRect(p1.x, p1.y, p2.x-p1.x, p2.y-p1.y);
      }
    }
  }
});

// ---------- UI ----------
function buildUI(){
  const modes = document.getElementById("modes");
  for(const k in MODES){
    const b = document.createElement("button");
    b.textContent = MODES[k].label; b.dataset.k = k;
    b.onclick = () => setMode(k);
    modes.appendChild(b);
  }
  const vs = document.getElementById("viewsel");
  vs.innerHTML = `<option value="score">Composite score</option>` +
    LAYERS.map(L2=>`<option value="${L2.k}">${L2.label}</option>`).join("");
  vs.onchange = () => { state.view = vs.value; canvasLayer.redraw(); };
  setMode("gw");
}

function setMode(k){
  state.mode = k;
  const m = MODES[k];
  state.w = {...m.w};
  state.on = {}; for(const L2 of LAYERS) state.on[L2.k] = true;
  state.gates = {...m.gates};
  document.querySelectorAll("#modes button").forEach(b=>b.classList.toggle("on", b.dataset.k===k));
  document.getElementById("modenote").textContent = m.note;
  renderWeights(); renderGates(); refresh();
}

function renderWeights(){
  const el = document.getElementById("weights"); el.innerHTML = "";
  for(const L2 of LAYERS){
    const row = document.createElement("div");
    row.className = "wrow" + (state.on[L2.k] ? "" : " off");
    row.innerHTML = `<input type="checkbox" ${state.on[L2.k]?"checked":""}>
      <label>${L2.label}</label>
      <input type="range" min="${L2.dual?-100:0}" max="100" value="${state.w[L2.k]}">
      <span class="val">${state.w[L2.k]}</span>`;
    const [cb,,rg,val] = row.children;
    cb.onchange = () => { state.on[L2.k] = cb.checked; row.classList.toggle("off", !cb.checked); refresh(); };
    rg.oninput = () => { state.w[L2.k] = +rg.value; val.textContent = rg.value; refresh(); };
    el.appendChild(row);
    const hint = document.createElement("div");
    hint.className = "hint"; hint.textContent = L2.hint;
    el.appendChild(hint);
  }
}

function renderGates(){
  const el = document.getElementById("gates");
  el.innerHTML = `
    <div class="gaterow"><label>Max terrain relief</label>
      <input id="g_rel" type="range" min="50" max="800" step="25" value="${state.gates.relief}"><span class="val">${state.gates.relief} m</span></div>
    <div class="gaterow"><label>Min developable share</label>
      <input id="g_dev" type="range" min="0" max="0.9" step="0.05" value="${state.gates.dev}"><span class="val">${Math.round(state.gates.dev*100)}%</span></div>`;
  el.querySelector("#g_rel").oninput = e => { state.gates.relief = +e.target.value; e.target.nextElementSibling.textContent = e.target.value+" m"; refresh(); };
  el.querySelector("#g_dev").oninput = e => { state.gates.dev = +e.target.value; e.target.nextElementSibling.textContent = Math.round(e.target.value*100)+"%"; refresh(); };
}

function refresh(){
  computeScores();
  canvasLayer.redraw();
  renderTop();
  if(selected >= 0) showDetail(selected);
}

function renderTop(){
  const idx = scores.map((s,i)=>[s,i]).filter(x=>x[0]>=0).sort((a,b)=>b[0]-a[0]);
  const picks = [];
  for(const [s,i] of idx){
    if(picks.length >= 10) break;
    const c = DATA.cells[i];
    if(picks.some(p => dist(c, DATA.cells[p]) < 45)) continue;
    picks.push(i);
  }
  document.getElementById("topcount").textContent = `(${idx.length} cells pass gates)`;
  const el = document.getElementById("toplist"); el.innerHTML = "";
  picks.forEach((i,r)=>{
    const c = DATA.cells[i], R = REGIONS[c[F.CCAA]];
    const d = document.createElement("div");
    d.className = "site";
    d.innerHTML = `<b>${r+1}. ${DATA.cities[c[F.CITYI]][0]} area</b> <span class="score-badge">${scores[i].toFixed(0)}</span>
      <div class="m">${R.name} · ${c[F.EY]} kWh/kWp · ${Math.round(devFrac(c)*100)}% developable · ${c[F.DCITY]} km to city</div>`;
    d.onclick = () => { select(i); map.flyTo([c[F.LAT], c[F.LON]], 9); };
    el.appendChild(d);
  });
  if(!picks.length) el.innerHTML = `<div class="m" style="color:var(--dim)">No cells pass the current gates — relax them.</div>`;
}

function dist(a,b){
  const p = Math.PI/180;
  const h = 0.5 - Math.cos((b[F.LAT]-a[F.LAT])*p)/2 + Math.cos(a[F.LAT]*p)*Math.cos(b[F.LAT]*p)*(1-Math.cos((b[F.LON]-a[F.LON])*p))/2;
  return 12742*Math.asin(Math.sqrt(h));
}

function select(i){ selected = i; canvasLayer.redraw(); showDetail(i); }

function showDetail(i){
  const c = DATA.cells[i], R = REGIONS[c[F.CCAA]], m = MODES[state.mode];
  const sz = sizing(m.it, c[F.EY]);
  const own = devHa(c), avail = state.mode === "gw" ? clusterHa[i] || own : own;
  const fits = avail >= sz.ha;
  let contrib = "";
  for(const L2 of LAYERS){
    if(!state.on[L2.k]) continue;
    const w = state.w[L2.k], n = L2.norm(c), eff = w>=0 ? n : 1-n;
    contrib += `<tr><td>${L2.label}<div class="bar"><i style="width:${Math.round(eff*100)}%"></i></div></td>
      <td>${L2.fmt(c)}<br><span style="font-size:10px">w ${w>0?"+":""}${w} → ${(eff*100).toFixed(0)}</span></td></tr>`;
  }
  const isa = [["#8c2f39",c[F.FMAX],"Máxima (excluded)"],["#c95d3f",c[F.FMUYALTA],"Muy alta"],["#e0a13f",c[F.FALTA],"Alta"],["#a4c05b",c[F.FMOD],"Moderada"],["#4caf7d",c[F.FBAJA],"Baja"]];
  const el = document.getElementById("detail");
  el.style.display = "block";
  el.innerHTML = `
    <span class="close" onclick="document.getElementById('detail').style.display='none';selected=-1;canvasLayer.redraw()">×</span>
    <h1>${DATA.cities[c[F.CITYI]][0]} area <span style="color:var(--dim);font-weight:400">· ${R.name}</span></h1>
    <div class="sub">${c[F.LAT].toFixed(2)}, ${c[F.LON].toFixed(2)} · elev ${c[F.ELEV]} m · cell ~94 km²</div>
    <div style="font-size:26px;font-weight:700;color:var(--accent)">${scores[i]>=0?scores[i].toFixed(0):"—"}<span style="font-size:12px;color:var(--dim)"> /100 composite ${scores[i]<0?"(fails gates)":""}</span></div>

    <h2>Layer contributions</h2>
    <table class="kv">${contrib}</table>

    <h2>BYOP build math — ${m.label}</h2>
    <table class="kv">
      <tr><td>IT load / campus load (PUE ${PUE})</td><td>${m.it} / ${Math.round(sz.loadMW)} MW</td></tr>
      <tr><td>PV for ${SOLAR_SHARE*100}% solar share at ${c[F.EY]} kWh/kWp</td><td>${Math.round(sz.mwp).toLocaleString()} MWp</td></tr>
      <tr><td>Battery (≈${BESS_MWH_PER_MW} MWh/MW load)</td><td>${Math.round(sz.bess).toLocaleString()} MWh</td></tr>
      <tr><td>Land required (${HA_PER_MWP} ha/MWp + site)</td><td>${Math.round(sz.ha).toLocaleString()} ha</td></tr>
      <tr><td>Developable land ${state.mode==="gw" ? "in cell + 8 neighbors" : "in this cell"}</td><td>${Math.round(avail).toLocaleString()} ha</td></tr>
    </table>
    <div style="margin-top:8px"><span class="badge ${fits?"b-good":"b-bad"}">${fits ? "Land requirement met" : "Insufficient contiguous land"}</span></div>

    <h2>Environmental sensitivity (MITECO 25 m)</h2>
    <div class="stack">${isa.map(x=>`<span style="width:${x[1]*100}%;background:${x[0]}" title="${x[2]}"></span>`).join("")}</div>
    <div style="font-size:10.5px;color:var(--dim)">${isa.map(x=>`${x[2]} ${(x[1]*100).toFixed(0)}%`).join(" · ")}</div>

    <h2>Regulatory reception — ${R.score}/100 <span style="color:var(--dim)">(${R.confidence} confidence)</span></h2>
    <div class="dossier">
      <b>${R.instrument}</b>
      <p style="margin:6px 0">${R.dossier}</p>
      ${R.sources.map(s=>`<a href="${s}" target="_blank">${new URL(s).hostname}</a>`).join("<br>")}
      <div class="conf" style="margin-top:6px">Interpretive layer: the dossier is the data; the score is its one-axis projection. Confidence reflects primary-source verification.</div>
    </div>

    <h2>Context</h2>
    <table class="kv">
      <tr><td>Nearest DC project</td><td>${DATA.dcs[c[F.DCI]][0]} · ${c[F.DDC]} km</td></tr>
      <tr><td style="color:var(--dim);font-size:11px" colspan="2">${DATA.dcs[c[F.DCI]][3]}</td></tr>
      <tr><td>Nearest city ≥100k</td><td>${DATA.cities[c[F.CITYI]][0]} · ${c[F.DCITY]} km</td></tr>
      <tr><td>Terrain relief (4×4 subgrid)</td><td>${c[F.RELIEF]<0?"pending":c[F.RELIEF]+" m"}</td></tr>
    </table>
    <div class="footnote">Next diligence step for this cell: cadastral parcel lookup (Sede Electrónica del Catastro) for ownership and legal state of the specific developable parcels.</div>`;
}

// ---------- boot ----------
(async function(){
  const [cellsR, regR] = await Promise.all([fetch("data/cells.json"), fetch("data/regions.json")]);
  DATA = await cellsR.json(); REGIONS = await regR.json();
  DATA.cells.forEach((c,i)=> byKey.set(key(c[F.LAT], c[F.LON]), i));

  map = L.map("map", {zoomControl:true}).setView([40.2, -3.6], 6);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
    {attribution:"© OpenStreetMap, © CARTO", maxZoom: 12}).addTo(map);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png",
    {pane:"shadowPane", maxZoom: 12}).addTo(map);

  canvasLayer = new CellLayer(); map.addLayer(canvasLayer);
  for(const d of DATA.dcs){
    L.circleMarker([d[1], d[2]], {radius:5, color:"#fff", weight:1.5, fillColor:"#e05d5d", fillOpacity:0.9})
      .bindTooltip(`<b>${d[0]}</b><br>${d[3]}`).addTo(map);
  }
  map.on("click", e => {
    const lat = Math.floor(e.latlng.lat/0.1)*0.1+0.05, lon = Math.floor(e.latlng.lng/0.1)*0.1+0.05;
    const i = byKey.get(key(lat,lon));
    if(i !== undefined) select(i);
  });
  buildUI();
})();
