const METRICS = {
  co2: ["CO₂", "ppm", 0],
  pm1_0: ["PM1.0", "µg/m³", 1],
  pm2_5: ["PM2.5", "µg/m³", 1],
  pm4_0: ["PM4.0", "µg/m³", 1],
  pm10: ["PM10", "µg/m³", 1],
  voc: ["VOC", "", 0],
  nox: ["NOx", "", 0],
  temperature: ["Temperature", "°C", 1],
  humidity: ["Humidity", "%", 1],
  pressure: ["Pressure", "hPa", 1],
  rssi: ["RSSI", "dBm", 0],
  nowcast_aqi: ["NowCast AQI", "", 0],
  esp_temperature: ["ESP temperature", "°C", 1],
  carbon_monoxide: ["Carbon monoxide", "ppm", 2],
  methane: ["Methane", "ppm", 2],
  ethanol: ["Ethanol", "ppm", 2],
  hydrogen: ["Hydrogen", "ppm", 2],
  ammonia: ["Ammonia", "ppm", 2],
  nitrogen_dioxide: ["Nitrogen dioxide", "ppm", 2],
  pm_0_3_to_1: ["PM 0.3–1", "µg/m³", 1],
  pm_1_to_2_5: ["PM 1–2.5", "µg/m³", 1],
  pm_2_5_to_4: ["PM 2.5–4", "µg/m³", 1],
  pm_4_to_10: ["PM 4–10", "µg/m³", 1],
};
const CARD_METRICS = ["co2", "pm2_5", "voc", "temperature", "humidity", "rssi"];
const state = { sensors: new Map(), detailId: null, history: [] };
const grid = document.querySelector("#sensor-grid");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function formatValue(key, value) {
  const definition = METRICS[key];
  if (!definition || value === null || value === undefined) return "—";
  return `${Number(value).toFixed(definition[2])}${definition[1] ? ` ${definition[1]}` : ""}`;
}

function formatAge(timestamp) {
  if (!timestamp) return "Never";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (seconds < 60) return `${seconds} second${seconds === 1 ? "" : "s"} ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

function sensorCard(sensor) {
  const selected = document.querySelector("#metric-filter").value;
  const keys = selected === "all" ? CARD_METRICS : [selected];
  const metricRows = keys.map(key => {
    const value = sensor.metrics?.[key];
    return `<div><dt>${METRICS[key][0]}</dt><dd class="${value == null ? "unavailable" : ""}">${formatValue(key, value)}</dd></div>`;
  }).join("");
  return `
    <article class="sensor-card ${sensor.online ? "" : "offline"}" data-id="${escapeHtml(sensor.id)}">
      <div class="card-head">
        <h3>${escapeHtml(sensor.name)}</h3>
        <span class="status ${sensor.online ? "online" : "offline"}">${sensor.online ? "ONLINE" : "OFFLINE"}</span>
      </div>
      <div class="hostname">${escapeHtml(sensor.hostname)}</div>
      <p class="updated ${sensor.online ? "" : "stale-note"}">
        ${sensor.online ? "Last update" : "Stale · last data"}: ${formatAge(sensor.last_seen)}
      </p>
      <dl class="metric-list">${metricRows}</dl>
      <a class="card-link" href="/sensor/${encodeURIComponent(sensor.id)}">View history →</a>
    </article>`;
}

function renderNetworkStatus() {
  const online = [...state.sensors.values()].filter(sensor => sensor.online).length;
  document.querySelector("#network-status").textContent =
    `${online} of ${state.sensors.size} sensors online · Live`;
}

function renderGrid() {
  const query = document.querySelector("#search").value.trim().toLowerCase();
  const sensors = [...state.sensors.values()]
    .filter(sensor => `${sensor.name} ${sensor.hostname}`.toLowerCase().includes(query))
    .sort((a, b) => a.id.localeCompare(b.id));
  grid.innerHTML = sensors.map(sensorCard).join("") || '<p class="empty">No matching sensors.</p>';
  renderNetworkStatus();
}

function showOverview(push = false) {
  state.detailId = null;
  document.querySelector("#overview").hidden = false;
  document.querySelector("#detail").hidden = true;
  if (push) history.pushState({}, "", "/");
  renderGrid();
}

async function showDetail(sensorId, push = false) {
  state.detailId = sensorId;
  if (push) history.pushState({}, "", `/sensor/${encodeURIComponent(sensorId)}`);
  document.querySelector("#overview").hidden = true;
  document.querySelector("#detail").hidden = false;
  const response = await fetch(`/api/sensors/${encodeURIComponent(sensorId)}`);
  if (!response.ok) return showOverview();
  const sensor = await response.json();
  state.sensors.set(sensor.id, sensor);
  renderDetail(sensor);
  await loadHistory();
}

function renderDetail(sensor) {
  document.querySelector("#detail-name").textContent = sensor.name;
  document.querySelector("#detail-hostname").textContent = sensor.hostname;
  document.querySelector("#detail-state").innerHTML =
    `<span class="status ${sensor.online ? "online" : "offline"}">${sensor.online ? "ONLINE" : "OFFLINE · STALE DATA"}</span>`;
  const available = Object.entries(sensor.metrics || {}).filter(([, value]) => value != null);
  document.querySelector("#detail-metrics").innerHTML = available.map(([key, value]) => `
    <div class="detail-metric">
      <div class="label">${escapeHtml(METRICS[key]?.[0] || key)}</div>
      <div class="value">${escapeHtml(formatValue(key, value))}</div>
    </div>`).join("");
  const metadata = [
    ["Last valid telemetry", sensor.last_seen ? new Date(sensor.last_seen).toLocaleString() : "Never"],
    ["IP address", sensor.ip_address || "Not exposed"],
    ["MAC", sensor.mac || "Not exposed by firmware"],
    ["Model", sensor.model || "Not exposed"],
    ["Apollo firmware", sensor.firmware_version || "Not exposed"],
    ["ESPHome", sensor.esphome_version || "Not exposed"],
    ["SSE connection", sensor.sse_connected ? "Connected" : "Disconnected"],
  ];
  document.querySelector("#detail-metadata").innerHTML =
    metadata.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("");
  const metricSelect = document.querySelector("#chart-metric");
  const current = metricSelect.value;
  metricSelect.innerHTML = available
    .filter(([key]) => METRICS[key])
    .map(([key]) => `<option value="${key}">${METRICS[key][0]}</option>`).join("");
  if ([...metricSelect.options].some(option => option.value === current)) metricSelect.value = current;
  else if ([...metricSelect.options].some(option => option.value === "co2")) metricSelect.value = "co2";
}

async function loadHistory() {
  if (!state.detailId) return;
  const metric = document.querySelector("#chart-metric").value || "co2";
  const hours = document.querySelector("#chart-range").value;
  const response = await fetch(`/api/sensors/${encodeURIComponent(state.detailId)}/history?metric=${metric}&hours=${hours}`);
  if (!response.ok) return;
  state.history = (await response.json()).readings;
  drawChart(metric);
}

function drawChart(metric) {
  const canvas = document.querySelector("#history-chart");
  const empty = document.querySelector("#chart-empty");
  const points = state.history.filter(row => row[metric] != null);
  empty.hidden = points.length > 0;
  canvas.hidden = points.length === 0;
  if (!points.length) return;
  const rect = canvas.parentElement.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * ratio);
  canvas.height = Math.max(1, rect.height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = rect.width, height = rect.height;
  const pad = { left: 56, right: 18, top: 18, bottom: 34 };
  const values = points.map(point => Number(point[metric]));
  let min = Math.min(...values), max = Math.max(...values);
  if (min === max) { min -= 1; max += 1; }
  const start = new Date(points[0].timestamp).getTime();
  const end = new Date(points.at(-1).timestamp).getTime();
  const span = Math.max(1, end - start);
  ctx.font = "11px system-ui"; ctx.fillStyle = "#65706a"; ctx.strokeStyle = "#e2e5e2"; ctx.lineWidth = 1;
  for (let index = 0; index <= 4; index++) {
    const y = pad.top + (height - pad.top - pad.bottom) * index / 4;
    const value = max - (max - min) * index / 4;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    ctx.fillText(value.toFixed(METRICS[metric]?.[2] ?? 1), 4, y + 4);
  }
  ctx.strokeStyle = "#345f78"; ctx.lineWidth = 2; ctx.beginPath();
  points.forEach((point, index) => {
    const x = pad.left + (new Date(point.timestamp).getTime() - start) / span * (width - pad.left - pad.right);
    const y = pad.top + (max - Number(point[metric])) / (max - min) * (height - pad.top - pad.bottom);
    index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#65706a";
  ctx.fillText(new Date(start).toLocaleString(), pad.left, height - 8);
  const endLabel = new Date(end).toLocaleString();
  const labelWidth = ctx.measureText(endLabel).width;
  ctx.fillText(endLabel, width - pad.right - labelWidth, height - 8);
}

function connectLive() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/api/ws`);
  socket.onopen = renderNetworkStatus;
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === "snapshot") message.sensors.forEach(sensor => state.sensors.set(sensor.id, sensor));
    if (message.type === "sensor") state.sensors.set(message.sensor.id, message.sensor);
    renderNetworkStatus();
    if (state.detailId && message.sensor?.id === state.detailId) renderDetail(message.sensor);
    else if (!state.detailId) renderGrid();
  };
  socket.onclose = () => {
    document.querySelector("#network-status").textContent = "Live connection interrupted · reconnecting";
    setTimeout(connectLive, 2000);
  };
}

async function initialize() {
  const response = await fetch("/api/sensors");
  (await response.json()).forEach(sensor => state.sensors.set(sensor.id, sensor));
  const match = location.pathname.match(/^\/sensor\/([^/]+)$/);
  if (match) await showDetail(decodeURIComponent(match[1]));
  else showOverview();
  connectLive();
}

document.querySelector("#search").addEventListener("input", renderGrid);
document.querySelector("#metric-filter").addEventListener("change", renderGrid);
document.querySelector("#back").addEventListener("click", () => showOverview(true));
document.querySelector("#chart-metric").addEventListener("change", loadHistory);
document.querySelector("#chart-range").addEventListener("change", loadHistory);
grid.addEventListener("click", event => {
  const link = event.target.closest(".card-link");
  if (!link) return;
  event.preventDefault();
  showDetail(link.closest(".sensor-card").dataset.id, true);
});
window.addEventListener("popstate", () => {
  const match = location.pathname.match(/^\/sensor\/([^/]+)$/);
  match ? showDetail(decodeURIComponent(match[1])) : showOverview();
});
window.addEventListener("resize", () => {
  if (state.detailId) drawChart(document.querySelector("#chart-metric").value);
});
initialize();
