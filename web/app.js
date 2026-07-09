/* Spain BYOP siting dashboard v2 — all scoring client-side, recomputes live.
   v2: continuous MITECO ISA (PV+wind), wind resource + hybrid mode, capex model,
   satellite basemap, Catastro parcel overlay + click-through parcel lookup. */
"use strict";

const F = {LAT:0, LON:1, CCAA:2, EY:3, ELEV:4, RELIEF:5, FVALID:6, FMAX:7, FMUYALTA:8, FALTA:9, FMOD:10, FBAJA:11,
           DCITY:12, CITYI:13, DDC:14, DCI:15, ISAV:16, EOLV:17, EOLDEV:18, PATCH:19, WS:20, PRECIP:21, PVMW:22};
const DC_COLORS = {operating:"#e05d5d", construction:"#ff9f43", announced:"#ffe95e", land:"#b388ff"};
const CELL_HA = 9400;
const PUE = 1.15, HA_PER_MWP = 2, HA_PER_WIND_MW = 5, BESS_H = {solar:10, hybrid:7};
// Screening-grade unit costs, M EUR (2026): PV incl. BOS; wind onshore; 4h-class BESS; backup engines; meseta agri land.
const COST = {pv:0.55, wind:1.15, bess:0.20, backup:0.45, land_ha:0.012};

const MODES = {
  gw:   {label:"1 GW solar", it:1000, mix:{pv:0.9, wind:0, backup:0.1},
         note:"Hyperscale campus, PV+BESS only. Land need computed from each cell's own yield; aggregates neighboring cells (~30 km).",
         w:{solar:90, env:80, terrain:70, reg:85, city:-30, dc:20, wind:0, eolv:0, rain:0, pvx:0}, gates:{relief:300, dev:0.35}},
  gwh:  {label:"1 GW hybrid", it:1000, mix:{pv:0.55, wind:0.35, backup:0.1},
         note:"PV + on-site wind. Wind firms winter/night supply and cuts battery + land; needs wind resource AND wind permitting headroom.",
         w:{solar:70, env:70, terrain:60, reg:85, city:-30, dc:20, wind:60, eolv:50, rain:0, pvx:0}, gates:{relief:300, dev:0.35}},
  mw100:{label:"100 MW", it:100, mix:{pv:0.9, wind:0, backup:0.1},
         note:"Large single-site campus; fits inside one cell's developable land in most of the meseta.",
         w:{solar:80, env:70, terrain:60, reg:70, city:20, dc:30, wind:0, eolv:0, rain:0, pvx:0}, gates:{relief:350, dev:0.15}},
  edge: {label:"10 MW edge", it:10, mix:{pv:0.9, wind:0, backup:0.1},
         note:"Regional/edge site; proximity to labor and fiber flips to a positive.",
         w:{solar:50, env:30, terrain:30, reg:40, city:80, dc:10, wind:0, eolv:0, rain:0, pvx:0}, gates:{relief:500, dev:0.05}},
};

const clamp = v => Math.max(0, Math.min(1, v));
const devFrac = c => (c[F.FMOD]+c[F.FBAJA]) * c[F.FVALID];
const devHa = c => devFrac(c) * CELL_HA;
const windCF = ws50 => clamp(((ws50*1.13)-3.5)/9) * 0.48;  // crude hub-height extrapolation + linearized power curve

const LAYERS = [
  {k:"solar", label:"Solar yield", dual:false, hint:"PVGIS specific yield, optimal fixed tilt",
   fmt:c=>c[F.EY]+" kWh/kWp·yr", norm:c=>clamp((c[F.EY]-1250)/(1800-1250))},
  {k:"env", label:"Env. sensitivity (PV)", dual:false, hint:"MITECO continuous ISA value, 0–10 (10 = least sensitive)",
   fmt:c=>c[F.ISAV].toFixed(1)+"/10 · "+Math.round(devFrac(c)*100)+"% developable", norm:c=>c[F.ISAV]/10},
  {k:"terrain", label:"Buildable terrain", dual:false, hint:"Intra-cell elevation range (lower = flatter)",
   fmt:c=>c[F.RELIEF]+" m relief", norm:c=>1-clamp(c[F.RELIEF]/600)},
  {k:"reg", label:"Regulatory reception", dual:false, hint:"Per-region score from primary-source dossier",
   fmt:c=>REGIONS[c[F.CCAA]].score+"/100 · "+REGIONS[c[F.CCAA]].name, norm:c=>REGIONS[c[F.CCAA]].score/100},
  {k:"wind", label:"Wind resource", dual:false, hint:"NASA POWER 50 m mean wind (0.5° grid — screening only)",
   fmt:c=>c[F.WS]+" m/s · CF≈"+Math.round(windCF(c[F.WS])*100)+"%", norm:c=>clamp((c[F.WS]-4)/3.5)},
  {k:"eolv", label:"Env. sensitivity (wind)", dual:false, hint:"MITECO continuous wind ISA, 0–10 — wind permitting is tighter than PV",
   fmt:c=>c[F.EOLV].toFixed(1)+"/10 · "+Math.round(c[F.EOLDEV]*100)+"% developable", norm:c=>c[F.EOLV]/10},
  {k:"rain", label:"Rain (soiling relief)", dual:false, hint:"Annual precip. Second-order: rain cleans panels (~1–3% yield in dry areas); cloud impact is already inside PVGIS yield",
   fmt:c=>c[F.PRECIP]+" mm/yr", norm:c=>clamp((c[F.PRECIP]-250)/550)},
  {k:"city", label:"City proximity", dual:true, hint:"Labor/fiber (+) vs pushback exposure (−); negative weight prefers remote",
   fmt:c=>c[F.DCITY]+" km to "+DATA.cities[c[F.CITYI]][0], norm:c=>1-clamp(c[F.DCITY]/150)},
  {k:"dc", label:"DC cluster proximity", dual:true, hint:"Validated corridor (+) vs uncontested whitespace (−)",
   fmt:c=>c[F.DDC]+" km to "+DATA.dcs[c[F.DCI]][0], norm:c=>1-clamp(c[F.DDC]/250)},
  {k:"pvx", label:"Existing PV build-out", dual:true, hint:"OSM-mapped solar in cell: follow proven zones (+) or hunt whitespace (−)",
   fmt:c=>c[F.PVMW]+" MW mapped in cell", norm:c=>clamp(c[F.PVMW]/150)},
];

let DATA, REGIONS, FARMS, DCJSON, map, canvasLayer, baseDark, baseSat, catWMS;
let state = {mode:"gw", w:{}, on:{}, gates:{}, view:"score", showCells:true, showFarms:true};
let scores = [], pass = [], clusterHa = [], capex = [], capexDomain = [8,16], byKey = new Map();
let selected = -1, clickPt = null;

function sizing(mode, c){
  const it = mode.it, mix = mode.mix, load = it * PUE, E = load * 8760;
  const mwp = E * mix.pv / c[F.EY];
  const cf = windCF(c[F.WS]);
  const windMW = mix.wind > 0 && cf > 0.05 ? E * mix.wind / (8760 * cf) : 0;
  const bess = load * (mix.wind > 0 ? BESS_H.hybrid : BESS_H.solar);
  const ha = mwp * HA_PER_MWP + windMW * HA_PER_WIND_MW + it * 0.03;
  const capexM = mwp*COST.pv + windMW*COST.wind + bess*COST.bess + load*COST.backup + ha*COST.land_ha;
  return {load, mwp, windMW, cf, bess, ha, capexM, perMW: capexM/it};
}

function computeScores(){
  const g = state.gates, m = MODES[state.mode];
  const refCell = []; refCell[F.EY] = 1750; refCell[F.WS] = 6;
  const needHa = sizing(m, refCell).ha;
  pass = DATA.cells.map(c =>
    c[F.FVALID] >= 0.3 && c[F.RELIEF] <= g.relief && devFrac(c) >= g.dev &&
    (m.mix.wind === 0 || windCF(c[F.WS]) > 0.05));
  clusterHa = DATA.cells.map((c,i)=>{
    if(!pass[i]) return 0;
    let ha = devHa(c);
    for(const j of neighbors(i)) if(pass[j]) ha += devHa(DATA.cells[j]);
    return ha;
  });
  if(m.it >= 1000) pass = pass.map((p,i)=> p && clusterHa[i] >= needHa);
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
  capex = DATA.cells.map((c,i)=> pass[i] ? sizing(m, c).perMW : NaN);
  const vals = capex.filter(v=>!isNaN(v)).sort((a,b)=>a-b);
  if(vals.length) capexDomain = [vals[Math.floor(vals.length*0.02)], vals[Math.floor(vals.length*0.98)]];
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

function viridis(t){
  t = clamp(t);
  const st = [[44,26,77],[32,144,140],[122,209,81],[253,231,37]];
  const x = t*3, i = Math.min(2, Math.floor(x)), f = x-i;
  const a = st[i], b = st[i+1];
  return `rgb(${a.map((v,k)=>Math.round(v+(b[k]-v)*f)).join(",")})`;
}

const CellLayer = L.Layer.extend({
  onAdd(m){
    this._c = L.DomUtil.create("canvas", "", m.getPane("overlayPane"));
    this._ctx = this._c.getContext("2d");
    m.on("moveend zoomend resize", this.redraw, this);
    this.redraw();
  },
  redraw(){
    const m = map, size = m.getSize(), z = m.getZoom();
    const tl = m.containerPointToLayerPoint([0,0]);
    L.DomUtil.setPosition(this._c, tl);
    this._c.width = size.x; this._c.height = size.y;
    if(!state.showCells) return;
    const ctx = this._ctx;
    const layerView = LAYERS.find(L2 => L2.k === state.view);
    const zoomFade = z >= 15 ? 0 : z >= 12 ? 0.35 : 1;  // let satellite/parcels show through when zoomed in
    for(let i=0; i<DATA.cells.length; i++){
      const c = DATA.cells[i];
      const p1 = m.latLngToContainerPoint([c[F.LAT]+0.05, c[F.LON]-0.05]);
      const p2 = m.latLngToContainerPoint([c[F.LAT]-0.05, c[F.LON]+0.05]);
      if(p2.x < 0 || p1.x > size.x || p2.y < 0 || p1.y > size.y) continue;
      let fill, alpha = 0.72;
      if(state.view === "score"){
        const s = scores[i];
        if(s === undefined || s < 0){ fill = "#3a3f4a"; alpha = 0.35; }
        else fill = viridis((s-35)/50);
      } else if(state.view === "capex"){
        const v = capex[i];
        if(isNaN(v)){ fill = "#3a3f4a"; alpha = 0.35; }
        else fill = viridis(1 - (v-capexDomain[0])/(capexDomain[1]-capexDomain[0]));  // yellow = cheap
      } else {
        fill = viridis(layerView.norm(c)); alpha = 0.7;
      }
      alpha *= zoomFade;
      if(alpha > 0){
        ctx.globalAlpha = alpha; ctx.fillStyle = fill;
        ctx.fillRect(p1.x, p1.y, Math.max(1.2, p2.x-p1.x-0.4), Math.max(1.2, p2.y-p1.y-0.4));
      }
      if(i === selected){
        ctx.globalAlpha = 1; ctx.strokeStyle = "#fff"; ctx.lineWidth = 2;
        ctx.strokeRect(p1.x, p1.y, p2.x-p1.x, p2.y-p1.y);
      }
    }
    if(state.showFarms && FARMS){
      ctx.globalAlpha = 0.85; ctx.fillStyle = "#43d9f5"; ctx.strokeStyle = "#0b3a44"; ctx.lineWidth = 0.5;
      for(const f of FARMS){
        const p = m.latLngToContainerPoint([f[0], f[1]]);
        if(p.x < -5 || p.x > size.x+5 || p.y < -5 || p.y > size.y+5) continue;
        const r = Math.min(9, 1.2 + Math.sqrt(f[2])/4);
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.283); ctx.fill(); ctx.stroke();
      }
    }
  }
});

function buildUI(){
  const modes = document.getElementById("modes");
  for(const k in MODES){
    const b = document.createElement("button");
    b.textContent = MODES[k].label; b.dataset.k = k;
    b.onclick = () => setMode(k);
    modes.appendChild(b);
  }
  const vs = document.getElementById("viewsel");
  vs.innerHTML = `<option value="score">Composite score</option><option value="capex">Power capex €/MW IT</option>` +
    LAYERS.map(L2=>`<option value="${L2.k}">${L2.label}</option>`).join("");
  vs.onchange = () => {
    state.view = vs.value;
    document.getElementById("lg0").textContent = vs.value==="capex" ? "expensive" : "low";
    document.getElementById("lg1").textContent = vs.value==="capex" ? "cheap" : "high";
    canvasLayer.redraw();
  };
  document.getElementById("bm_sat").onchange = e => {
    if(e.target.checked){ map.removeLayer(baseDark); map.addLayer(baseSat); }
    else { map.removeLayer(baseSat); map.addLayer(baseDark); }
  };
  document.getElementById("ov_cat").onchange = e => {
    if(e.target.checked) map.addLayer(catWMS); else map.removeLayer(catWMS);
  };
  document.getElementById("ov_cells").onchange = e => { state.showCells = e.target.checked; canvasLayer.redraw(); };
  document.getElementById("ov_pv").onchange = e => { state.showFarms = e.target.checked; canvasLayer.redraw(); };
  setMode("gw");
}

function setMode(k){
  state.mode = k;
  const m = MODES[k];
  state.w = {...m.w};
  state.on = {}; for(const L2 of LAYERS) state.on[L2.k] = m.w[L2.k] !== 0;
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
    rg.oninput = () => { state.w[L2.k] = +rg.value; val.textContent = rg.value; if(!state.on[L2.k] && +rg.value){cb.checked=true;state.on[L2.k]=true;row.classList.remove("off");} refresh(); };
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
  drawScatter();
  saveHash();
  if(selected >= 0) showDetail(selected);
}

// ---------- shareable state ----------
function saveHash(){
  const h = {m:state.mode, v:state.view, w:state.w, on:state.on, g:state.gates};
  history.replaceState(null, "", "#" + encodeURIComponent(JSON.stringify(h)));
}
function restoreHash(){
  try{
    if(location.hash.length < 3) return;
    const h = JSON.parse(decodeURIComponent(location.hash.slice(1)));
    if(!MODES[h.m]) return;
    setMode(h.m);
    Object.assign(state.w, h.w); Object.assign(state.on, h.on); Object.assign(state.gates, h.g);
    state.view = h.v || "score";
    document.getElementById("viewsel").value = state.view;
    renderWeights(); renderGates(); refresh();
  }catch(e){}
}

// ---------- validation: model score vs existing build-out ----------
function drawScatter(){
  const cv = document.getElementById("scatter");
  if(!cv) return;
  const ctx = cv.getContext("2d"), W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);
  const pts = [];
  let totMW = 0;
  for(let i = 0; i < DATA.cells.length; i++){
    if(scores[i] < 0) continue;
    const mw = DATA.cells[i][F.PVMW];
    totMW += mw;
    pts.push([scores[i], mw, i]);
  }
  if(!pts.length){ document.getElementById("valstat").textContent = "No cells pass gates."; return; }
  const yMax = Math.log10(1 + Math.max(...pts.map(p=>p[1]), 10));
  ctx.fillStyle = "#43d9f5";
  for(const [s, mw, i] of pts){
    ctx.globalAlpha = mw > 0 ? 0.75 : 0.18;
    const x = 6 + (s/100)*(W-12), y = H-6 - (Math.log10(1+mw)/yMax)*(H-12);
    ctx.fillRect(x-1.5, y-1.5, 3, 3);
  }
  ctx.globalAlpha = 1;
  // stat: how much of the existing fleet sits in the model's top-quintile cells?
  const sorted = [...pts].sort((a,b)=>b[0]-a[0]);
  const q = Math.max(1, Math.floor(sorted.length/5));
  const topMW = sorted.slice(0, q).reduce((a,p)=>a+p[1], 0);
  document.getElementById("valstat").innerHTML =
    `Top-20% scored cells hold <b>${totMW ? Math.round(100*topMW/totMW) : 0}%</b> of the ${(totMW/1000).toFixed(1)} GW of OSM-mapped PV in passing cells — ` +
    `x: composite score, y: existing MW (log). Bright dots = cells with built PV.`;
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
      <div class="m">${R.name} · ${c[F.EY]} kWh/kWp · ${Math.round(devFrac(c)*100)}% developable · ${capex[i]?capex[i].toFixed(1)+" M€/MW":""}</div>`;
    d.onclick = () => { select(i, null); map.flyTo([c[F.LAT], c[F.LON]], 10); };
    el.appendChild(d);
  });
  if(!picks.length) el.innerHTML = `<div class="m" style="color:var(--dim)">No cells pass the current gates — relax them.</div>`;
}

function dist(a,b){
  const p = Math.PI/180;
  const h = 0.5 - Math.cos((b[F.LAT]-a[F.LAT])*p)/2 + Math.cos(a[F.LAT]*p)*Math.cos(b[F.LAT]*p)*(1-Math.cos((b[F.LON]-a[F.LON])*p))/2;
  return 12742*Math.asin(Math.sqrt(h));
}

function select(i, pt){
  selected = i;
  clickPt = pt || {lat: DATA.cells[i][F.LAT], lng: DATA.cells[i][F.LON]};
  canvasLayer.redraw(); showDetail(i);
  lookupParcel(clickPt);
}

function showDetail(i){
  const c = DATA.cells[i], R = REGIONS[c[F.CCAA]], m = MODES[state.mode];
  const sz = sizing(m, c);
  const own = devHa(c), avail = m.it >= 1000 ? clusterHa[i] || own : own;
  const fits = avail >= sz.ha;
  let contrib = "";
  for(const L2 of LAYERS){
    if(!state.on[L2.k]) continue;
    const w = state.w[L2.k], n = L2.norm(c), eff = w>=0 ? n : 1-n;
    contrib += `<tr><td>${L2.label}<div class="bar"><i style="width:${Math.round(eff*100)}%"></i></div></td>
      <td>${L2.fmt(c)}<br><span style="font-size:10px">w ${w>0?"+":""}${w} → ${(eff*100).toFixed(0)}</span></td></tr>`;
  }
  const isa = [["#8c2f39",c[F.FMAX],"Máxima (excluded)"],["#c95d3f",c[F.FMUYALTA],"Muy alta"],["#e0a13f",c[F.FALTA],"Alta"],["#a4c05b",c[F.FMOD],"Moderada"],["#4caf7d",c[F.FBAJA],"Baja"]];
  const windRow = sz.windMW > 0 ? `<tr><td>Wind for ${Math.round(m.mix.wind*100)}% share (CF≈${Math.round(sz.cf*100)}%)</td><td>${Math.round(sz.windMW).toLocaleString()} MW</td></tr>` : "";
  const el = document.getElementById("detail");
  el.style.display = "block";
  el.innerHTML = `
    <span class="close" onclick="document.getElementById('detail').style.display='none';selected=-1;canvasLayer.redraw()">×</span>
    <h1>${DATA.cities[c[F.CITYI]][0]} area <span style="color:var(--dim);font-weight:400">· ${R.name}</span></h1>
    <div class="sub">${c[F.LAT].toFixed(2)}, ${c[F.LON].toFixed(2)} · elev ${c[F.ELEV]} m · cell ~94 km²</div>
    <div style="font-size:26px;font-weight:700;color:var(--accent)">${scores[i]>=0?scores[i].toFixed(0):"—"}<span style="font-size:12px;color:var(--dim)"> /100 composite ${scores[i]<0?"(fails gates)":""}</span></div>

    <h2>Parcel at clicked point <span style="color:var(--dim);text-transform:none">(Catastro, live)</span></h2>
    <div class="dossier" id="parcel">Looking up referencia catastral…</div>

    <h2>Layer contributions</h2>
    <table class="kv">${contrib}</table>

    <h2>BYOP build math — ${m.label}</h2>
    <table class="kv">
      <tr><td>IT load / campus load (PUE ${PUE})</td><td>${m.it} / ${Math.round(sz.load)} MW</td></tr>
      <tr><td>PV for ${Math.round(m.mix.pv*100)}% share at ${c[F.EY]} kWh/kWp</td><td>${Math.round(sz.mwp).toLocaleString()} MWp</td></tr>
      ${windRow}
      <tr><td>Battery (${m.mix.wind>0?BESS_H.hybrid:BESS_H.solar} MWh/MW load)</td><td>${Math.round(sz.bess).toLocaleString()} MWh</td></tr>
      <tr><td>Land required</td><td>${Math.round(sz.ha).toLocaleString()} ha</td></tr>
      <tr><td>Developable land ${m.it>=1000 ? "in cell + 8 neighbors" : "in this cell"}</td><td>${Math.round(avail).toLocaleString()} ha</td></tr>
      <tr><td>Largest contiguous developable patch touching cell</td><td>${c[F.PATCH].toLocaleString()} ha</td></tr>
    </table>
    <div style="margin-top:8px"><span class="badge ${fits?"b-good":"b-bad"}">${fits ? "Land requirement met" : "Insufficient contiguous land"}</span></div>

    <h2>Power capex (screening)</h2>
    <table class="kv">
      <tr><td>PV ${Math.round(sz.mwp).toLocaleString()} MWp × ${COST.pv} M€</td><td>${Math.round(sz.mwp*COST.pv).toLocaleString()} M€</td></tr>
      ${sz.windMW>0?`<tr><td>Wind ${Math.round(sz.windMW).toLocaleString()} MW × ${COST.wind} M€</td><td>${Math.round(sz.windMW*COST.wind).toLocaleString()} M€</td></tr>`:""}
      <tr><td>BESS ${Math.round(sz.bess).toLocaleString()} MWh × ${COST.bess} M€</td><td>${Math.round(sz.bess*COST.bess).toLocaleString()} M€</td></tr>
      <tr><td>Backup ${Math.round(sz.load).toLocaleString()} MW × ${COST.backup} M€</td><td>${Math.round(sz.load*COST.backup).toLocaleString()} M€</td></tr>
      <tr><td>Land ${Math.round(sz.ha).toLocaleString()} ha × ${COST.land_ha*1000} k€</td><td>${Math.round(sz.ha*COST.land_ha).toLocaleString()} M€</td></tr>
      <tr><td><b>Total power system</b> (DC building excluded — site-invariant)</td><td><b>${Math.round(sz.capexM).toLocaleString()} M€ · ${sz.perMW.toFixed(1)} M€/MW IT</b></td></tr>
    </table>

    <h2>Environmental sensitivity (MITECO 25 m)</h2>
    <div class="stack">${isa.map(x=>`<span style="width:${x[1]*100}%;background:${x[0]}" title="${x[2]}"></span>`).join("")}</div>
    <div style="font-size:10.5px;color:var(--dim)">${isa.map(x=>`${x[2]} ${(x[1]*100).toFixed(0)}%`).join(" · ")}</div>
    <div style="font-size:11px;color:var(--dim);margin-top:4px">Continuous ISA — PV: <b>${c[F.ISAV].toFixed(1)}/10</b> · wind: <b>${c[F.EOLV].toFixed(1)}/10</b> (10 = least sensitive; classes gate, the continuous value ranks within class)</div>

    <h2>Regulatory reception — ${R.score}/100 <span style="color:var(--dim)">(${R.confidence} confidence)</span></h2>
    <div class="dossier">
      <b>${R.instrument}</b>
      <p style="margin:6px 0">${R.dossier}</p>
      ${R.sources.map(s=>`<a href="${s}" target="_blank">${new URL(s).hostname}</a>`).join("<br>")}
    </div>

    <h2>Context</h2>
    <table class="kv">
      <tr><td>Nearest DC project</td><td>${DATA.dcs[c[F.DCI]][0]} · ${c[F.DDC]} km</td></tr>
      <tr><td style="color:var(--dim);font-size:11px" colspan="2">${DATA.dcs[c[F.DCI]][3]}</td></tr>
      <tr><td>Nearest city ≥100k</td><td>${DATA.cities[c[F.CITYI]][0]} · ${c[F.DCITY]} km</td></tr>
      <tr><td>Wind 50 m / precip</td><td>${c[F.WS]} m/s · ${c[F.PRECIP]} mm/yr</td></tr>
      <tr><td>Existing PV mapped in cell (OSM)</td><td>${c[F.PVMW]>0 ? "<b>"+c[F.PVMW]+" MW</b> — proven zone" : "none — whitespace"}</td></tr>
    </table>
    <div class="footnote">Cost constants are screening-grade 2026 figures; edit COST in app.js. Wind CF from 0.5° mean speed is indicative only — a real site needs a met campaign or Global Wind Atlas microdata.</div>`;
}

async function lookupParcel(pt){
  const el = () => document.getElementById("parcel");
  const gmaps = `https://www.google.com/maps/@${pt.lat.toFixed(5)},${pt.lng.toFixed(5)},2500m/data=!3m1!1e3`;
  try{
    const r = await fetch(`https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCoordenadas.svc/json/Consulta_RCCOOR?CoorX=${pt.lng.toFixed(6)}&CoorY=${pt.lat.toFixed(6)}&SRS=EPSG:4326`);
    const j = await r.json();
    const co = j.Consulta_RCCOORResult?.coordenadas?.coord?.[0];
    if(!co?.pc){ if(el()) el().innerHTML = `No parcel at this exact point (unregistered/public land). <a href="${gmaps}" target="_blank">Satellite view ↗</a>`; return; }
    const rc = co.pc.pc1 + co.pc.pc2;
    let html = `<b>${rc}</b><br>${co.ldt || ""}`;
    try{
      const r2 = await fetch(`https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json/Consulta_DNPRC?RefCat=${rc}`);
      const j2 = await r2.json();
      const bi = j2.consulta_dnprcResult?.bico?.bi;
      const finca = j2.consulta_dnprcResult?.bico?.finca;
      if(bi){
        const cls = bi.idbi?.cn === "RU" ? "Rústica (rural)" : "Urbana";
        const uso = bi.debi?.luso || "—";
        const ha = finca?.dff?.ss ? (finca.dff.ss/10000).toFixed(1)+" ha" : "";
        html += `<br>Class: <b>${cls}</b> · Use: <b>${uso}</b>${ha?` · Surface: <b>${ha}</b>`:""}`;
        const sub = (j2.consulta_dnprcResult?.bico?.lspr || []).slice(0,4)
          .map(x=>x.spr?.dspr ? `${x.spr.dspr.dcc || ""} ${x.spr.dspr.ssp ? (x.spr.dspr.ssp/10000).toFixed(1)+" ha" : ""}` : "").filter(Boolean);
        if(sub.length) html += `<br><span style="font-size:11px;color:var(--dim)">Cultivos: ${sub.join(" · ")}</span>`;
        const igraf = finca?.infgraf?.igraf;
        html += `<br><a href="${igraf || "https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx?refcat="+rc}" target="_blank">Sede Catastro ↗</a> · <a href="${gmaps}" target="_blank">Satellite ↗</a> · <a href="https://sigpac.mapa.gob.es/fega/visor/" target="_blank">SIGPAC visor ↗</a>`;
      }
    }catch(e){ html += `<br><a href="${gmaps}" target="_blank">Satellite ↗</a>`; }
    if(el()) el().innerHTML = html + `<div class="conf" style="margin-top:5px">Zoom in with the Catastro overlay on to see parcel boundaries; click precisely on a plot to identify it.</div>`;
  }catch(e){
    if(el()) el().innerHTML = `Catastro service unreachable right now. <a href="${gmaps}" target="_blank">Satellite view ↗</a>`;
  }
}

(async function(){
  if(window.__CELLS){  // data shipped as script files -> works from file:// with no server
    DATA = window.__CELLS; REGIONS = window.__REGIONS; FARMS = window.__FARMS; DCJSON = window.__DCS;
  } else {
    const V = "?v=5";
    const [cellsR, regR, farmR, dcR] = await Promise.all([
      fetch("data/cells.json"+V), fetch("data/regions.json"+V),
      fetch("data/solar_farms.json"+V), fetch("data/datacenters.json"+V)]);
    DATA = await cellsR.json(); REGIONS = await regR.json();
    FARMS = await farmR.json(); DCJSON = await dcR.json();
  }
  DATA.cells.forEach((c,i)=> byKey.set(key(c[F.LAT], c[F.LON]), i));

  map = L.map("map", {zoomControl:true, maxZoom:19}).setView([40.2, -3.6], 6);
  baseDark = L.layerGroup([
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png", {attribution:"© OpenStreetMap, © CARTO", maxZoom:19}),
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {pane:"shadowPane", maxZoom:19}),
  ]).addTo(map);
  baseSat = L.layerGroup([
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {attribution:"© Esri, Maxar", maxZoom:19}),
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png", {pane:"shadowPane", maxZoom:19}),
  ]);
  catWMS = L.tileLayer.wms("https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx", {
    layers:"Catastro", format:"image/png", transparent:true, minZoom:13, maxZoom:19, attribution:"© DG Catastro"});

  canvasLayer = new CellLayer(); map.addLayer(canvasLayer);
  const dcGroups = {};
  for(const d of DCJSON){
    const g = dcGroups[d.status] || (dcGroups[d.status] = L.layerGroup().addTo(map));
    L.circleMarker([d.lat, d.lon], {radius: d.src==="research" ? 5.5 : 3.5, color:"#fff", weight:1.2,
        fillColor: DC_COLORS[d.status] || "#e05d5d", fillOpacity:0.95})
      .bindTooltip(`<b>${d.name}</b><br><i>${d.status}</i> · ${d.note}`).addTo(g);
  }
  document.querySelectorAll(".dcst").forEach(cb => cb.onchange = () => {
    const g = dcGroups[cb.value];
    if(g) cb.checked ? map.addLayer(g) : map.removeLayer(g);
  });
  map.on("click", e => {
    const lat = Math.floor(e.latlng.lat/0.1)*0.1+0.05, lon = Math.floor(e.latlng.lng/0.1)*0.1+0.05;
    const i = byKey.get(key(lat,lon));
    if(i !== undefined) select(i, e.latlng);
  });
  buildUI();
  restoreHash();
})();
