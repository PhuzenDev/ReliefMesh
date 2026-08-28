import { useState } from "react";
import { ingestReports } from "../../api/client.js";
import { queueReport, isOnline } from "../../offline/offlineQueue.js";
import LocationPicker from "./LocationPicker.jsx";

// backend/app/models/schemas.py: SourceType / NeedType enums
const SOURCES = ["call", "sms", "field_team", "sensor"];
const NEED_TYPES = ["medical", "rescue", "food_water", "shelter", "evacuation", "unknown"];

const EMPTY = {
  source: "call",
  location: null, // { lat, lon } — set via the map/search picker, never typed
  text: "",
  need_type: "unknown",
  people_affected: "",
};

// There's no GET /reports on the backend — reports are pooled server-side
// and only surface once /cycle/run turns them into evidence clusters and
// mission proposals. So this panel is intake, not a feed: submit reports
// here, then use the toolbar's "Run cycle" to see what they produce.
export default function ReportIntakeForm({ onIngested }) {
  const [form, setForm] = useState(EMPTY);
  const [status, setStatus] = useState(null); // { kind: 'ok'|'error'|'queued', message }
  const [submitting, setSubmitting] = useState(false);

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function buildReport() {
    if (!form.location) {
      throw new Error("Pick a location on the map or search for one");
    }
    return {
      source: form.source,
      lat: form.location.lat,
      lon: form.location.lon,
      text: form.text || null,
      need_type: form.need_type,
      people_affected: form.people_affected ? parseInt(form.people_affected, 10) : null,
    };
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setStatus(null);
    try {
      const report = buildReport();
      if (!isOnline()) {
        const queuedCount = queueReport(report);
        setStatus({ kind: "queued", message: `Offline — queued (${queuedCount} pending sync)` });
        onIngested?.(report, { queued: true });
      } else {
        const result = await ingestReports([report]);
        setStatus({ kind: "ok", message: `Added to pool (${result.pool_size} pending cycle)` });
        onIngested?.(report, { poolSize: result.pool_size });
      }
      setForm(EMPTY);
    } catch (err) {
      setStatus({ kind: "error", message: err.message });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex h-full flex-col">
      <div className="flex items-center justify-between px-1 pb-3">
        <span className="eyebrow">New report intake</span>
      </div>

      <div className="grid flex-1 auto-rows-min grid-cols-2 gap-3 px-1">
        <label className="col-span-1 flex flex-col gap-1 text-xs text-fog-300">
          Source
          <select
            value={form.source}
            onChange={(e) => set("source", e.target.value)}
            className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
          >
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
        </label>

        <label className="col-span-1 flex flex-col gap-1 text-xs text-fog-300">
          Need type
          <select
            value={form.need_type}
            onChange={(e) => set("need_type", e.target.value)}
            className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
          >
            {NEED_TYPES.map((n) => (
              <option key={n} value={n}>
                {n.replace("_", " / ")}
              </option>
            ))}
          </select>
        </label>

        <LocationPicker value={form.location} onChange={(loc) => set("location", loc)} />

        <label className="col-span-2 flex flex-col gap-1 text-xs text-fog-300">
          Report text
          <textarea
            value={form.text}
            onChange={(e) => set("text", e.target.value)}
            rows={2}
            placeholder="Elderly resident collapsed, needs medical attention"
            className="resize-none rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
          />
        </label>

        <label className="col-span-1 flex flex-col gap-1 text-xs text-fog-300">
          People affected
          <input
            type="number"
            min="0"
            value={form.people_affected}
            onChange={(e) => set("people_affected", e.target.value)}
            placeholder="1"
            className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
          />
        </label>

        <div className="col-span-1 flex items-end">
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded bg-signal-cyan/15 px-3 py-1.5 text-sm font-medium text-signal-cyan transition hover:bg-signal-cyan/25 disabled:opacity-50"
          >
            {submitting ? "Submitting…" : "Submit report"}
          </button>
        </div>
      </div>

      {status && (
        <div
          className={`px-1 pt-3 font-mono text-[15px] ${
            status.kind === "error"
              ? "text-triage-immediate"
              : status.kind === "queued"
                ? "text-signal-amber"
                : "text-triage-minor"
          }`}
        >
          {status.message}
        </div>
      )}
    </form>
  );
}
