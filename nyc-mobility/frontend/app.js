const API = new URLSearchParams(location.search).get("api") || "";
const $ = s => document.querySelector(s);
const FIELDS = ["date_from","date_to","hour_from","hour_to","borough","day_type","min_distance","max_distance","min_fare","max_fare"];
const state = { zone: "", zoneName: "", metric: "pickups", sort: "pickup_ts", order: "desc", page: 1, pages: 1 };
const DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const BUCKETS = [["late_night","Late night (0-5)"],["morning_rush","Morning rush (6-9)"],["midday","Midday (10-15)"],["evening_rush","Evening rush (16-19)"],["evening","Evening (20-23)"]];
const COLORS = ["#17445a","#2f7f93","#f6b800","#c9722a","#8a9a5b"];
const fmt = (v, d = 0) => v == null ? "–" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });

function qs(extra = {}) {
  const p = new URLSearchParams();
  FIELDS.forEach(f => { const v = $("#" + f).value; if (v !== "") p.set(f, v); });
  if (state.zone) p.set("pu_zone", state.zone);
  Object.entries(extra).forEach(([k, v]) => p.set(k, v));
  return p.toString();
}
async function get(path, extra) {
  const r = await fetch(`${API}/api/${path}?${qs(extra)}`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
  return r.json();
}

/* ---------- KPIs ---------- */
async function loadKpis() {
  const s = await get("summary");
  const items = [[fmt(s.trips), "trips"], ["$" + fmt(s.avg_fare, 2), "average fare"], [fmt(s.avg_distance, 1) + " mi", "average distance"],
    [fmt(s.avg_duration, 0) + " min", "average duration"], [fmt(s.avg_speed, 1) + " mph", "average speed"], [fmt(s.avg_tip_pct, 1) + "%", "average card tip"]];
  $("#kpis").innerHTML = items.map(([b, l]) => `<div class="kpi"><b>${b}</b><span>${l}</span></div>`).join("");
}

/* ---------- map ---------- */
let map, layer, geo, zoneData = {};
const lerp = (a, b, t) => a + (b - a) * t;
const stops = [[0, [251,240,200]], [.4, [246,184,0]], [1, [23,68,90]]];
function color(t) {
  for (let i = 1; i < stops.length; i++) if (t <= stops[i][0]) {
    const [t0, c0] = stops[i-1], [t1, c1] = stops[i], u = (t - t0) / (t1 - t0);
    return `rgb(${c0.map((v, k) => Math.round(lerp(v, c1[k], u))).join(",")})`;
  }
  return "rgb(23,68,90)";
}
const METRIC_LABEL = { pickups: "pickups", dropoffs: "dropoffs", avg_fare: "avg fare ($)", avg_speed: "avg speed (mph)" };
async function initMap() {
  map = L.map("map", { zoomControl: true }).setView([40.72, -73.95], 10);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
    { attribution: "&copy; OpenStreetMap, &copy; CARTO", maxZoom: 15 }).addTo(map);
  geo = await (await fetch(`${API}/api/geojson`)).json();
}
function drawMap(zones) {
  zoneData = Object.fromEntries(zones.map(z => [z.zone_id, z]));
  const m = state.metric, vals = zones.map(z => z[m]).filter(v => v != null);
  const lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1;
  const count = m === "pickups" || m === "dropoffs";
  const scale = v => { if (v == null || hi === lo) return 0; const t = (v - lo) / (hi - lo); return count ? Math.sqrt(t) : t; };
  if (layer) map.removeLayer(layer);
  layer = L.geoJSON(geo, {
    style: f => { const z = zoneData[f.properties.id], v = z ? z[m] : null;
      return { weight: f.properties.id == state.zone ? 3 : .6, color: f.properties.id == state.zone ? "#1d2a35" : "#ffffff",
               fillColor: v == null ? "#e3e6e1" : color(scale(v)), fillOpacity: v == null ? .4 : .85 }; },
    onEachFeature: (f, l) => {
      l.bindTooltip(() => { const z = zoneData[f.properties.id];
        return `<b>${f.properties.name}</b><br>${f.properties.borough}<br>` + (z ?
          `${fmt(z.pickups)} pickups · ${fmt(z.dropoffs)} dropoffs<br>Fare $${fmt(z.avg_fare, 2)} · ${fmt(z.avg_speed, 1)} mph` : "No trips"); }, { sticky: true });
      l.on("click", () => { state.zone = f.properties.id; state.zoneName = f.properties.name; refresh(); });
    }
  }).addTo(map);
  const unit = m === "avg_fare" ? "$" : "";
  $("#legMin").textContent = `${unit}${fmt(lo, count ? 0 : 1)} ${METRIC_LABEL[m]}`;
  $("#legMax").textContent = `${unit}${fmt(hi, count ? 0 : 1)}`;
}

/* ---------- charts ---------- */
let hourChart, tipChart;
async function loadHourly() {
  const d = await get("hourly"), labels = [...Array(24).keys()].map(h => h + ":00");
  const by = Object.fromEntries(d.map(r => [r.hour, r]));
  const trips = labels.map((_, h) => by[h]?.trips ?? 0), speed = labels.map((_, h) => by[h]?.avg_speed ?? null);
  const cfg = { data: { labels, datasets: [
      { type: "bar", label: "Trips", data: trips, backgroundColor: "#f6b800", yAxisID: "y", order: 2 },
      { type: "line", label: "Avg mph", data: speed, borderColor: "#17445a", backgroundColor: "#17445a", tension: .3, pointRadius: 2, yAxisID: "y2", order: 1 }] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: { y: { title: { display: true, text: "Trips" }, beginAtZero: true }, y2: { position: "right", title: { display: true, text: "mph" }, grid: { drawOnChartArea: false }, beginAtZero: true },
                x: { ticks: { maxTicksLimit: 12 } } } } };
  if (hourChart) { hourChart.data = cfg.data; hourChart.update(); } else hourChart = new Chart($("#hourChart"), cfg);
}
async function loadTips() {
  const d = await get("tips");
  const boroughs = [...new Set(d.map(r => r.borough))].sort();
  const idx = Object.fromEntries(d.map(r => [r.borough + "|" + r.bucket, r.avg_tip_pct]));
  const data = { labels: boroughs, datasets: BUCKETS.map(([k, name], i) => ({ label: name, backgroundColor: COLORS[i], data: boroughs.map(b => idx[b + "|" + k] ?? null) })) };
  const opts = { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, title: { display: true, text: "Tip %" } } }, plugins: { legend: { labels: { boxWidth: 12 } } } };
  if (tipChart) { tipChart.data = data; tipChart.update(); } else tipChart = new Chart($("#tipChart"), { type: "bar", data, options: opts });
}
async function loadHeat() {
  const d = await get("heatmap"), grid = {}; let max = 1;
  d.forEach(r => { grid[r.dow + "|" + r.hour] = r.trips; max = Math.max(max, r.trips); });
  let h = `<span></span>` + [...Array(24).keys()].map(i => `<span class="lab">${i % 3 === 0 ? i : ""}</span>`).join("");
  DAYS.forEach((day, dow) => {
    h += `<span class="lab">${day}</span>`;
    for (let hr = 0; hr < 24; hr++) { const v = grid[dow + "|" + hr] || 0;
      h += `<span class="c" title="${day} ${hr}:00 – ${fmt(v)} trips" style="background:${v ? color(Math.sqrt(v / max)) : "#eef0ec"}"></span>`; }
  });
  $("#heat").innerHTML = h;
}

/* ---------- top K (custom algorithm on the server) ---------- */
async function loadTop() {
  const k = Math.max(1, Math.min(100, +$("#topK").value || 10));
  const d = await get("top", { kind: $("#topKind").value, k });
  const max = d.results.length ? d.results[0].trips : 1;
  $("#topTable tbody").innerHTML = d.results.length ? d.results.map((r, i) =>
    `<tr><td>${i + 1}</td><td>${r.label}</td><td class="r"><span class="bar" style="width:${Math.max(4, 120 * r.trips / max)}px"></span>${fmt(r.trips)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty">No trips match these filters.</td></tr>`;
  $("#topMeta").textContent = `Computed with a hand-written hash table and min-heap: ${fmt(d.rows_scanned)} trips scanned, ${fmt(d.distinct_keys)} distinct keys, ${d.elapsed_ms} ms.`;
}

/* ---------- trip table ---------- */
async function loadTrips() {
  const d = await get("trips", { sort: state.sort, order: state.order, page: state.page, page_size: 20 });
  state.pages = Math.max(1, Math.ceil(d.total / d.page_size));
  $("#tripTable tbody").innerHTML = d.rows.length ? d.rows.map(r => `<tr><td>${r.pickup_ts}</td><td>${r.pickup_zone}</td><td>${r.dropoff_zone}</td>
    <td class="r">${fmt(r.trip_distance, 1)}</td><td class="r">${fmt(r.duration_min, 0)}</td><td class="r">${fmt(r.speed_mph, 1)}</td>
    <td class="r">$${fmt(r.fare_amount, 2)}</td><td class="r">${r.tip_pct == null ? "cash/n.a." : fmt(r.tip_pct, 0) + "%"}</td><td class="r">$${fmt(r.total_amount, 2)}</td></tr>`).join("")
    : `<tr><td colspan="9" class="empty">No trips match. Widen the filters or clear the zone selection.</td></tr>`;
  $("#pageInfo").textContent = `Page ${state.page} of ${state.pages} · ${fmt(d.total)} trips`;
  $("#prev").disabled = state.page <= 1; $("#next").disabled = state.page >= state.pages;
  document.querySelectorAll("#tripTable th[data-s]").forEach(th => { th.classList.toggle("asc", th.dataset.s === state.sort && state.order === "asc"); th.classList.toggle("desc", th.dataset.s === state.sort && state.order === "desc"); });
}

/* ---------- orchestration ---------- */
async function refresh() {
  document.body.classList.add("loading");
  $("#zoneChip").hidden = !state.zone;
  $("#zoneChipText").textContent = state.zone ? `Pickup zone: ${state.zoneName}` : "";
  try {
    const [zones] = await Promise.all([get("zones"), loadKpis(), loadHourly(), loadTips(), loadHeat(), loadTop(), loadTrips()]);
    drawMap(zones);
  } catch (e) {
    $("#kpis").innerHTML = `<div class="empty">Couldn't load data: ${e.message}. Is the backend running and the database built?</div>`;
  }
  document.body.classList.remove("loading");
}

async function init() {
  const meta = await (await fetch(`${API}/api/meta`)).json();
  $("#borough").insertAdjacentHTML("beforeend", meta.boroughs.map(b => `<option>${b}</option>`).join(""));
  $("#date_from").min = $("#date_to").min = meta.date_min; $("#date_from").max = $("#date_to").max = meta.date_max;
  fetch(`${API}/api/cleaning`).then(r => r.json()).then(rows => {
    $("#cleanList").innerHTML = rows.filter(r => r.count > 0).map(r => `<li><b>${fmt(r.count)}</b> removed: ${r.description}</li>`).join("");
  });
  await initMap();
  await refresh();
}

$("#filterForm").addEventListener("submit", e => { e.preventDefault(); state.page = 1; refresh(); });
$("#reset").addEventListener("click", () => { $("#filterForm").reset(); state.zone = ""; state.page = 1; refresh(); });
$("#zoneClear").addEventListener("click", () => { state.zone = ""; state.page = 1; refresh(); });
$("#metricTabs").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return;
  state.metric = b.dataset.m; document.querySelectorAll("#metricTabs button").forEach(x => x.classList.toggle("on", x === b));
  get("zones").then(drawMap); });
$("#topKind").addEventListener("change", loadTop); $("#topK").addEventListener("change", loadTop);
$("#prev").addEventListener("click", () => { state.page--; loadTrips(); });
$("#next").addEventListener("click", () => { state.page++; loadTrips(); });
$("#tripTable thead").addEventListener("click", e => { const th = e.target.closest("th[data-s]"); if (!th) return;
  if (state.sort === th.dataset.s) state.order = state.order === "asc" ? "desc" : "asc"; else { state.sort = th.dataset.s; state.order = "desc"; }
  state.page = 1; loadTrips(); });
init();
