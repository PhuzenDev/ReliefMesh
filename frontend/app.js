/**
 * ReliefMesh Commander Console
 * =============================
 * Talks directly to the ReliefMesh FastAPI backend (backend/app/main.py).
 * No build step, no framework — plain fetch() + WebSocket.
 *
 * Endpoints used:
 *   GET    /health
 *   POST   /reports
 *   POST   /cycle/run
 *   POST   /cycle/replan?reason=...
 *   GET    /missions
 *   POST   /missions/{id}/decision
 *   POST   /offline/reports
 *   GET    /geo/state
 *   POST   /geo/roads/{road_id}/block|degrade|reopen
 *   WS     /ws/missions
 */

// ---------------------------------------------------------------------------
// Config (persisted in localStorage; edit via the ⚙ API button)
// ---------------------------------------------------------------------------
const STORAGE_KEYS = {
  apiBase: 'reliefmesh_api_base',
  decidedBy: 'reliefmesh_decided_by',
  offlineQueue: 'reliefmesh_offline_queue',
};

function safeGet(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v;
  } catch (e) {
    return fallback;
  }
}
function safeSet(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* storage unavailable — degrade quietly */ }
}

let API_BASE = safeGet(STORAGE_KEYS.apiBase, 'http://localhost:8000');
let DECIDED_BY = safeGet(STORAGE_KEYS.decidedBy, 'commander-1');

function wsBase() {
  return API_BASE.replace(/^http/, 'ws');
}

// ---------------------------------------------------------------------------
// Small state store
// ---------------------------------------------------------------------------
const state = {
  cards: [],          // [{proposal, check}]
  geo: null,           // {road_status, hazard_zones, shelters}
  reportsPooled: 0,    // best-effort counter (from /reports + /offline/reports responses)
  queue: loadQueue(),
  ws: null,
  wsRetryMs: 1500,
};

function loadQueue() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.offlineQueue);
    return raw ? JSON.parse(raw) : [];
  } catch (e) { return []; }
}
function saveQueue() {
  safeSet(STORAGE_KEYS.offlineQueue, JSON.stringify(state.queue));
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail || detail; } catch (e) {}
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---------------------------------------------------------------------------
// Activity log + toasts
// ---------------------------------------------------------------------------
function log(msg, level = 'info') {
  const el = document.getElementById('activity-log');
  const line = document.createElement('div');
  line.className = `log-line ${level}`;
  const t = new Date().toISOString().substr(11, 8);
  line.innerHTML = `<span class="t">${t}Z</span>${escapeHtml(msg)}`;
  el.appendChild(line);
  while (el.children.length > 60) el.removeChild(el.firstChild);
}

function toast(msg, level = 'info') {
  const root = document.getElementById('toast-root');
  const t = document.createElement('div');
  t.className = `toast ${level}`;
  t.textContent = msg;
  root.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ---------------------------------------------------------------------------
// Connection status
// ---------------------------------------------------------------------------
function setConnStatus(online) {
  const dot = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');
  dot.classList.remove('online', 'offline');
  dot.classList.add(online ? 'online' : 'offline');
  label.textContent = online ? `connected · ${API_BASE}` : `offline · queueing locally`;
}

async function pollHealth() {
  try {
    await api('/health');
    setConnStatus(true);
  } catch (e) {
    setConnStatus(false);
  }
}

// ---------------------------------------------------------------------------
// WebSocket — live mission board
// ---------------------------------------------------------------------------
function connectWs() {
  if (state.ws) {
    try { state.ws.close(); } catch (e) {}
  }
  let ws;
  try {
    ws = new WebSocket(`${wsBase()}/ws/missions`);
  } catch (e) {
    scheduleWsRetry();
    return;
  }
  state.ws = ws;

  ws.onopen = () => {
    log('WebSocket connected: /ws/missions', 'ok');
    state.wsRetryMs = 1500;
  };
  ws.onmessage = (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.type === 'missions_snapshot' || msg.type === 'missions_update') {
        state.cards = msg.cards || [];
        renderMissions();
        if (msg.type === 'missions_update') log('Mission board updated (push)', 'info');
      }
    } catch (e) {
      console.error('bad ws payload', e);
    }
  };
  ws.onclose = () => {
    log('WebSocket disconnected — retrying…', 'err');
    scheduleWsRetry();
  };
  ws.onerror = () => {
    try { ws.close(); } catch (e) {}
  };
}
function scheduleWsRetry() {
  setTimeout(connectWs, state.wsRetryMs);
  state.wsRetryMs = Math.min(state.wsRetryMs * 1.6, 20000);
}

// ---------------------------------------------------------------------------
// Missions
// ---------------------------------------------------------------------------
async function fetchMissions() {
  try {
    state.cards = await api('/missions');
    renderMissions();
  } catch (e) {
    log(`Failed to fetch /missions: ${e.message}`, 'err');
  }
}

async function runCycle() {
  const btn = document.getElementById('btn-run-cycle');
  btn.disabled = true;
  try {
    state.cards = await api('/cycle/run', { method: 'POST' });
    renderMissions();
    log(`Cycle run — ${state.cards.length} mission card(s)`, 'ok');
    toast('Cycle complete', 'ok');
  } catch (e) {
    log(`/cycle/run failed: ${e.message}`, 'err');
    toast(`Run cycle failed: ${e.message}`, 'err');
  } finally {
    btn.disabled = false;
  }
}

async function replan() {
  const reason = prompt('Reason for replan (e.g. "road closed", "crew unavailable"):', 'manual_replan');
  if (reason === null) return;
  try {
    state.cards = await api(`/cycle/replan?reason=${encodeURIComponent(reason)}`, { method: 'POST' });
    renderMissions();
    log(`Replan triggered: ${reason}`, 'ok');
    toast('Replan complete', 'ok');
  } catch (e) {
    log(`/cycle/replan failed: ${e.message}`, 'err');
    toast(`Replan failed: ${e.message}`, 'err');
  }
}

function fmtCoord(n) {
  return typeof n === 'number' ? n.toFixed(4) : n;
}

function renderMissions() {
  document.getElementById('stat-missions').textContent = state.cards.length;
  const list = document.getElementById('mission-list');
  if (!state.cards.length) {
    list.innerHTML = '<div class="empty-state">No missions yet. Submit field reports, then run a cycle.</div>';
    return;
  }
  list.innerHTML = state.cards.map(cardHtml).join('');

  // wire up action buttons
  list.querySelectorAll('[data-decide]').forEach((btn) => {
    btn.addEventListener('click', () => onDecide(btn.dataset.decide, btn.dataset.missionId));
  });
}

function cardHtml({ proposal: p, check: c }) {
  const feasible = c ? c.feasible : null;
  const infeasibleClass = feasible === false ? 'infeasible' : '';
  const supplies = Object.entries(p.supplies || {}).map(
    ([k, v]) => `<span class="supply-chip">${escapeHtml(k)} × ${v}</span>`
  ).join('');
  const violations = c && c.violations && c.violations.length
    ? `<div class="violations">${c.violations.map(v =>
        `<div class="violation ${v.severity}">[${v.severity.toUpperCase()}] ${escapeHtml(v.code)} — ${escapeHtml(v.message)}</div>`
      ).join('')}</div>`
    : '';
  const fairness = c && c.fairness_note ? `<div class="fairness-note">⚖ ${escapeHtml(c.fairness_note)}</div>` : '';
  const assumptions = p.assumptions && p.assumptions.length
    ? `<div class="assumptions">assumes: ${p.assumptions.map(escapeHtml).join('; ')}</div>` : '';

  const canDecide = ['proposed', 'checked', 'modified'].includes(p.status);

  return `
  <div class="mission-card ${infeasibleClass}">
    <div class="mcard-top">
      <div>
        <div class="mcard-id">${p.mission_id}</div>
        <div class="badges" style="margin-top:6px;">
          <span class="badge status-${p.status}">${p.status.toUpperCase()}</span>
          ${c ? `<span class="badge feasible-${feasible ? 'yes' : 'no'}">${feasible ? 'FEASIBLE' : 'BLOCKED'}</span>` : ''}
        </div>
      </div>
      <div class="mcard-score">priority ${Number(p.priority_score).toFixed(2)}${p.eta_minutes != null ? ` · eta ${Math.round(p.eta_minutes)}m` : ''}</div>
    </div>

    <div class="mcard-meta">
      <span>crew: <b>${p.crew_id || '—'}</b></span>
      <span>route: <b>${p.route_id || '—'}</b></span>
      <span>cluster: <b class="mono">${String(p.cluster_id).slice(0, 8)}</b></span>
    </div>

    ${supplies ? `<div class="supplies-row">${supplies}</div>` : ''}
    ${violations}
    ${fairness}
    ${assumptions}

    ${canDecide ? `
    <div class="mcard-actions">
      <button class="btn btn-small btn-approve" data-decide="approved" data-mission-id="${p.mission_id}">✓ Approve</button>
      <button class="btn btn-small btn-modify" data-decide="modified" data-mission-id="${p.mission_id}">✎ Modify</button>
      <button class="btn btn-small btn-reject" data-decide="rejected" data-mission-id="${p.mission_id}">✕ Reject</button>
    </div>` : ''}
  </div>`;
}

let pendingModifyMissionId = null;

function onDecide(decision, missionId) {
  if (decision === 'modified') {
    const card = state.cards.find(c => c.proposal.mission_id === missionId);
    pendingModifyMissionId = missionId;
    document.getElementById('mod-crew').value = card?.proposal.crew_id || '';
    document.getElementById('mod-route').value = card?.proposal.route_id || '';
    document.getElementById('mod-supplies').value = JSON.stringify(card?.proposal.supplies || {}, null, 2);
    showModal('modify-modal');
    return;
  }
  sendDecision(missionId, decision, null);
}

async function sendDecision(missionId, decision, modifications) {
  try {
    await api(`/missions/${missionId}/decision`, {
      method: 'POST',
      body: JSON.stringify({
        mission_id: missionId,
        decision,
        modifications,
        decided_by: DECIDED_BY,
      }),
    });
    log(`Mission ${missionId.slice(0, 8)} → ${decision.toUpperCase()} by ${DECIDED_BY}`, 'ok');
    toast(`Mission ${decision}`, 'ok');
    await fetchMissions(); // WS will also push an update; this covers no-WS fallback
  } catch (e) {
    log(`Decision failed for ${missionId}: ${e.message}`, 'err');
    toast(`Decision failed: ${e.message}`, 'err');
  }
}

// ---------------------------------------------------------------------------
// Field reports (online submit + offline queue)
// ---------------------------------------------------------------------------
function buildReportFromForm() {
  const lat = parseFloat(document.getElementById('f-lat').value);
  const lon = parseFloat(document.getElementById('f-lon').value);
  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    throw new Error('lat/lon are required');
  }
  const people = document.getElementById('f-people').value;
  const reliability = document.getElementById('f-reliability').value;

  return {
    source: document.getElementById('f-source').value,
    need_type: document.getElementById('f-need').value,
    lat, lon,
    text: document.getElementById('f-text').value || null,
    people_affected: people === '' ? null : parseInt(people, 10),
    source_reliability_hint: reliability === '' ? null : parseFloat(reliability),
    received_at: new Date().toISOString(),
  };
}

async function submitReport(evt) {
  evt.preventDefault();
  let report;
  try {
    report = buildReportFromForm();
  } catch (e) {
    toast(e.message, 'err');
    return;
  }

  try {
    const result = await api('/reports', { method: 'POST', body: JSON.stringify([report]) });
    state.reportsPooled = result.pool_size ?? state.reportsPooled + 1;
    document.getElementById('stat-reports').textContent = state.reportsPooled;
    log(`Report submitted (pool size ${state.reportsPooled})`, 'ok');
    toast('Report submitted', 'ok');
    document.getElementById('report-form').reset();
  } catch (e) {
    // Network / backend unreachable — fall back to the offline queue rather than losing the report.
    log(`Live submit failed (${e.message}) — queued offline instead`, 'err');
    queueReport(report);
    document.getElementById('report-form').reset();
  }
}

function queueReport(report) {
  state.queue.push(report);
  saveQueue();
  renderQueue();
  toast('Saved to offline queue', 'info');
}

function renderQueue() {
  document.getElementById('queue-count').textContent = state.queue.length;
  const list = document.getElementById('queue-list');
  if (!state.queue.length) {
    list.innerHTML = '<div class="empty-state small">Nothing queued.</div>';
    return;
  }
  list.innerHTML = state.queue.map((r, i) => `
    <div class="queue-item">
      <span>${escapeHtml(r.need_type)} · ${fmtCoord(r.lat)}, ${fmtCoord(r.lon)}</span>
      <span class="qmeta">${r.source} · ${new Date(r.received_at).toISOString().substr(11, 5)}Z</span>
    </div>
  `).join('');
}

async function syncQueue() {
  if (!state.queue.length) { toast('Queue is empty', 'info'); return; }
  const batch = [...state.queue];
  try {
    const cards = await api('/offline/reports', { method: 'POST', body: JSON.stringify(batch) });
    state.cards = cards;
    renderMissions();
    state.queue = [];
    saveQueue();
    renderQueue();
    log(`Synced ${batch.length} queued report(s) via /offline/reports`, 'ok');
    toast(`Synced ${batch.length} report(s)`, 'ok');
  } catch (e) {
    log(`Sync failed: ${e.message}`, 'err');
    toast(`Sync failed — still queued (${e.message})`, 'err');
  }
}

// ---------------------------------------------------------------------------
// Geo state — roads + shelters
// ---------------------------------------------------------------------------
async function fetchGeo() {
  try {
    state.geo = await api('/geo/state');
    renderGeo();
  } catch (e) {
    log(`Failed to fetch /geo/state: ${e.message}`, 'err');
  }
}

function renderGeo() {
  const roadList = document.getElementById('road-list');
  const shelterList = document.getElementById('shelter-list');
  if (!state.geo) return;

  const roads = Object.entries(state.geo.road_status || {});
  roadList.innerHTML = roads.length ? roads.map(([roadId, status]) => `
    <div class="road-row">
      <span class="rname">${escapeHtml(roadId)}</span>
      <span class="rstat r-${status}"><span class="rdot"></span>${status.toUpperCase()}</span>
      <div class="road-actions">
        <button class="btn btn-small btn-ghost" data-road-action="block" data-road-id="${roadId}">block</button>
        <button class="btn btn-small btn-ghost" data-road-action="degrade" data-road-id="${roadId}">degrade</button>
        <button class="btn btn-small btn-ghost" data-road-action="reopen" data-road-id="${roadId}">reopen</button>
      </div>
    </div>
  `).join('') : '<div class="empty-state small">No road data loaded.</div>';

  roadList.querySelectorAll('[data-road-action]').forEach((btn) => {
    btn.addEventListener('click', () => onRoadAction(btn.dataset.roadAction, btn.dataset.roadId));
  });

  const shelters = Object.values(state.geo.shelters || {});
  shelterList.innerHTML = shelters.length ? shelters.map((s) => {
    const pct = s.capacity ? Math.min(100, Math.round((s.occupied / s.capacity) * 100)) : 0;
    return `
    <div class="shelter-row">
      <span class="sname">${escapeHtml(s.shelter_id)}</span>
      <div class="occ-bar"><div class="occ-fill ${pct >= 90 ? 'full' : ''}" style="width:${pct}%"></div></div>
      <span class="mono">${s.occupied}/${s.capacity}</span>
    </div>`;
  }).join('') : '<div class="empty-state small">No shelter data loaded.</div>';
}

async function onRoadAction(action, roadId) {
  let reason = 'reported ' + (action === 'reopen' ? 'clear' : action);
  if (action !== 'reopen') {
    const r = prompt(`Reason for marking ${roadId} as ${action}:`, reason);
    if (r === null) return;
    reason = r;
  }
  try {
    await api(`/geo/roads/${encodeURIComponent(roadId)}/${action}${action !== 'reopen' ? `?reason=${encodeURIComponent(reason)}` : ''}`, { method: 'POST' });
    log(`Road ${roadId} → ${action.toUpperCase()}`, 'ok');
    toast(`${roadId} marked ${action}`, 'ok');
    await fetchGeo();
  } catch (e) {
    log(`Road action failed: ${e.message}`, 'err');
    toast(`Action failed: ${e.message}`, 'err');
  }
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------
function showModal(id) { document.getElementById(id).classList.remove('hidden'); }
function hideModal(id) { document.getElementById(id).classList.add('hidden'); }

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
function initSettingsModal() {
  document.getElementById('btn-settings').addEventListener('click', () => {
    document.getElementById('input-api-base').value = API_BASE;
    document.getElementById('input-decided-by').value = DECIDED_BY;
    showModal('settings-modal');
  });
  document.getElementById('btn-settings-cancel').addEventListener('click', () => hideModal('settings-modal'));
  document.getElementById('btn-settings-save').addEventListener('click', () => {
    const base = document.getElementById('input-api-base').value.trim().replace(/\/$/, '');
    const by = document.getElementById('input-decided-by').value.trim();
    if (base) { API_BASE = base; safeSet(STORAGE_KEYS.apiBase, base); }
    if (by) { DECIDED_BY = by; safeSet(STORAGE_KEYS.decidedBy, by); }
    hideModal('settings-modal');
    log(`Reconnecting to ${API_BASE}`, 'info');
    bootstrap();
  });
}

function initModifyModal() {
  document.getElementById('btn-modify-cancel').addEventListener('click', () => hideModal('modify-modal'));
  document.getElementById('btn-modify-save').addEventListener('click', () => {
    let supplies;
    try {
      supplies = JSON.parse(document.getElementById('mod-supplies').value || '{}');
    } catch (e) {
      toast('Supplies must be valid JSON', 'err');
      return;
    }
    const modifications = {
      crew_id: document.getElementById('mod-crew').value || null,
      route_id: document.getElementById('mod-route').value || null,
      supplies,
    };
    hideModal('modify-modal');
    if (pendingModifyMissionId) sendDecision(pendingModifyMissionId, 'modified', modifications);
  });
}

function initClock() {
  setInterval(() => {
    document.getElementById('clock').textContent = new Date().toISOString().substr(11, 8) + 'Z';
  }, 1000);
}

function initEventListeners() {
  document.getElementById('report-form').addEventListener('submit', submitReport);
  document.getElementById('btn-run-cycle').addEventListener('click', runCycle);
  document.getElementById('btn-replan').addEventListener('click', replan);
  document.getElementById('btn-refresh-missions').addEventListener('click', fetchMissions);
  document.getElementById('btn-refresh-geo').addEventListener('click', fetchGeo);
  document.getElementById('btn-sync-queue').addEventListener('click', syncQueue);
  document.getElementById('btn-use-location').addEventListener('click', () => {
    if (!navigator.geolocation) { toast('Geolocation not available', 'err'); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        document.getElementById('f-lat').value = pos.coords.latitude.toFixed(5);
        document.getElementById('f-lon').value = pos.coords.longitude.toFixed(5);
      },
      () => toast('Could not get location', 'err')
    );
  });

  window.addEventListener('online', () => { toast('Browser back online', 'ok'); pollHealth(); });
  window.addEventListener('offline', () => { setConnStatus(false); toast('Browser offline — reports will queue', 'err'); });
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
async function bootstrap() {
  await pollHealth();
  connectWs();
  await fetchMissions();
  await fetchGeo();
  renderQueue();
}

document.addEventListener('DOMContentLoaded', () => {
  initSettingsModal();
  initModifyModal();
  initClock();
  initEventListeners();
  setInterval(pollHealth, 8000);
  bootstrap();
});
