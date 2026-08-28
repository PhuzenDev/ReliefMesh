import { useState } from "react";

// backend/app/models/schemas.py CommanderDecision.modifications is an
// open Dict applied via setattr onto the MissionProposal — so only
// fields that already exist on MissionProposal are meaningful here.
export default function ModifyDecisionModal({ card, onCancel, onSubmit, submitting }) {
  const { proposal } = card;
  const [crewId, setCrewId] = useState(proposal.crew_id ?? "");
  const [routeId, setRouteId] = useState(proposal.route_id ?? "");
  const [etaMinutes, setEtaMinutes] = useState(proposal.eta_minutes ?? "");

  function handleSubmit(e) {
    e.preventDefault();
    const modifications = {};
    if (crewId !== (proposal.crew_id ?? "")) modifications.crew_id = crewId || null;
    if (routeId !== (proposal.route_id ?? "")) modifications.route_id = routeId || null;
    if (etaMinutes !== (proposal.eta_minutes ?? "")) {
      modifications.eta_minutes = etaMinutes === "" ? null : parseFloat(etaMinutes);
    }
    onSubmit(modifications);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/70 p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-xl border border-ink-600 bg-ink-800 p-5"
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="text-sm font-semibold text-fog-100">
            Modify {proposal.mission_id.toString().slice(0, 8)}
          </span>
        </div>

        <div className="space-y-3">
          <label className="flex flex-col gap-1 text-xs text-fog-300">
            Crew
            <input
              value={crewId}
              onChange={(e) => setCrewId(e.target.value)}
              placeholder="unassigned"
              className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-fog-300">
            Route
            <input
              value={routeId}
              onChange={(e) => setRouteId(e.target.value)}
              placeholder="not cleared"
              className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-fog-300">
            ETA (minutes)
            <input
              type="number"
              min="0"
              value={etaMinutes}
              onChange={(e) => setEtaMinutes(e.target.value)}
              className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
            />
          </label>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-3 py-1.5 text-xs font-medium text-fog-300 transition hover:bg-ink-700"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded bg-signal-cyan/15 px-3 py-1.5 text-xs font-medium text-signal-cyan transition hover:bg-signal-cyan/25 disabled:opacity-50"
          >
            {submitting ? "Saving…" : "Save modification"}
          </button>
        </div>
      </form>
    </div>
  );
}
