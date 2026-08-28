// A field client (or a dispatcher with a flaky connection) keeps
// submitting RawReports locally while offline; this queues them and
// flushes to POST /offline/reports (which preserves each report's
// original received_at) once connectivity returns.
//
// Kept deliberately simple — localStorage, not IndexedDB — since the
// backend already treats each flush as an idempotent batch replan.
// Swap for IndexedDB if the queue needs to survive across many MB of
// attachments or many days offline.

import { reconcileOfflineReports } from "../api/client.js";

const REPORTS_KEY = "reliefmesh.offline.reports";

export function queueReport(report) {
  const queue = loadQueuedReports();
  queue.push(report);
  localStorage.setItem(REPORTS_KEY, JSON.stringify(queue));
  return queue.length;
}

export function loadQueuedReports() {
  try {
    return JSON.parse(localStorage.getItem(REPORTS_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function clearQueuedReports() {
  localStorage.removeItem(REPORTS_KEY);
}

// Sends every queued report in one batch and clears the queue on success.
// Leaves the queue intact on failure so the caller can retry later.
export async function flushQueuedReports() {
  const queue = loadQueuedReports();
  if (queue.length === 0) return { flushed: 0, cards: null, reports: [] };
  const cards = await reconcileOfflineReports(queue);
  clearQueuedReports();
  return { flushed: queue.length, cards, reports: queue };
}

// True when the browser reports a live connection. Callers should still
// try/catch flushQueuedReports — this is a hint, not a guarantee.
export function isOnline() {
  return typeof navigator === "undefined" ? true : navigator.onLine;
}
