// Thin fetch wrapper over every route backend/app/main.py exposes.
// In dev, requests go through the vite proxy (see vite.config.js) to
// localhost:8000. Set VITE_API_BASE to point elsewhere (e.g. a deployed
// backend) — see .env.example.

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new Error(`${options.method ?? "GET"} ${path} -> ${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// -- health -----------------------------------------------------------
export const getHealth = () => request("/health");

// -- reports ------------------------------------------------------------
// Pools reports; does NOT replan by itself — pair with runCycle().
export const ingestReports = (reports) =>
  request("/reports", { method: "POST", body: JSON.stringify(reports) });

// -- pipeline cycles ----------------------------------------------------
export const runCycle = () => request("/cycle/run", { method: "POST" });
export const replan = (reason = "manual_replan") =>
  request(`/cycle/replan?reason=${encodeURIComponent(reason)}`, { method: "POST" });

// -- missions -------------------------------------------------------------
export const getMissions = () => request("/missions");
export const decideMission = (missionId, decision) =>
  request(`/missions/${missionId}/decision`, {
    method: "POST",
    body: JSON.stringify(decision),
  });

// -- offline reconciliation ----------------------------------------------
export const reconcileOfflineReports = (reports) =>
  request("/offline/reports", { method: "POST", body: JSON.stringify(reports) });
export const reconcileOfflineEvents = (events) =>
  request("/offline/events", { method: "POST", body: JSON.stringify(events) });

// -- geo --------------------------------------------------------------
export const getGeoState = () => request("/geo/state");
export const blockRoad = (roadId, reason = "reported blocked") =>
  request(`/geo/roads/${roadId}/block?reason=${encodeURIComponent(reason)}`, { method: "POST" });
export const degradeRoad = (roadId, reason = "reported degraded") =>
  request(`/geo/roads/${roadId}/degrade?reason=${encodeURIComponent(reason)}`, { method: "POST" });
export const reopenRoad = (roadId) =>
  request(`/geo/roads/${roadId}/reopen`, { method: "POST" });

// action is "block" | "degrade" | "reopen" — dispatches to the matching
// endpoint above. Kept as one function so callers (e.g. the map's road
// popups) don't need a switch statement of their own.
export function actOnRoad(roadId, action) {
  if (action === "block") return blockRoad(roadId);
  if (action === "degrade") return degradeRoad(roadId);
  if (action === "reopen") return reopenRoad(roadId);
  return Promise.reject(new Error(`Unknown road action: ${action}`));
}

// -- live updates -------------------------------------------------------
// Builds the ws:// or wss:// URL for /ws/missions from BASE (or the
// current page origin when BASE is unset, matching the same-origin proxy).
export function missionsSocketUrl() {
  if (BASE) {
    return BASE.replace(/^http/, "ws") + "/ws/missions";
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/missions`;
}
