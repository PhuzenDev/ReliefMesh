// Renders one { proposal, check } card exactly as returned by
// GET /missions / the /ws/missions socket (see Orchestrator._commander_view).
// Note: the API doesn't join cluster data onto mission cards, so there's
// no need_type/people_affected here — only what the proposal itself carries
// (crew, route, supplies, priority, ETA) plus the constraint verdict.

const TIER_STYLES = {
  immediate: {
    bar: "bg-triage-immediate",
    text: "text-triage-immediate",
    label: "Immediate",
    icon: "ti-alert-triangle",
  },
  delayed: { bar: "bg-triage-delayed", text: "text-triage-delayed", label: "Delayed", icon: "ti-clock" },
  minor: { bar: "bg-triage-minor", text: "text-triage-minor", label: "Minor", icon: "ti-circle-check" },
};

function triageTier(priorityScore) {
  if (priorityScore >= 0.75) return "immediate";
  if (priorityScore >= 0.45) return "delayed";
  return "minor";
}

export default function TriageCard({ card, onDecide, deciding }) {
  const { proposal, check } = card;
  const tier = triageTier(proposal.priority_score);
  const style = TIER_STYLES[tier];
  const blocked = check?.violations?.some((v) => v.severity === "block");
  const decided = proposal.status !== "proposed" && proposal.status !== "checked";
  const supplyEntries = Object.entries(proposal.supplies ?? {});

  return (
    <div className="triage-tag border border-ink-700 bg-ink-800/70">
      <div className={`absolute left-0 top-0 h-full w-[5px] ${style.bar}`} />

      <div className="flex items-start justify-between gap-3 px-4 pb-3 pt-3 pl-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-fog-100">
              {shortId(proposal.mission_id)}
            </span>
            <span className={`flex items-center gap-1 font-mono text-[14px] uppercase tracking-wide ${style.text}`}>
              <i className={`ti ${style.icon}`} aria-hidden="true" />
              {style.label}
            </span>
          </div>
          <div className="mt-0.5 text-sm text-fog-400">
            cluster {shortId(proposal.cluster_id)}
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-semibold text-fog-100">
            {proposal.priority_score.toFixed(2)}
          </div>
          <div className="eyebrow">priority</div>
        </div>
      </div>

      <div className="perforation mx-4" />

      <div className="grid grid-cols-2 gap-y-1.5 px-5 py-3 text-sm">
        <Field label="Crew" value={proposal.crew_id ?? "Unassigned"} dim={!proposal.crew_id} />
        <Field label="ETA" value={proposal.eta_minutes != null ? `${proposal.eta_minutes} min` : "—"} />
        <Field label="Route" value={proposal.route_id ?? "Not cleared"} dim={!proposal.route_id} />
        <Field label="Status" value={proposal.status} />
      </div>

      {supplyEntries.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-5 pb-3">
          {supplyEntries.map(([item, qty]) => (
            <span
              key={item}
              className="rounded bg-ink-700 px-2 py-0.5 font-mono text-[15px] text-fog-200"
            >
              {item} &times;{qty}
            </span>
          ))}
        </div>
      )}

      {proposal.assumptions?.length > 0 && (
        <div className="space-y-1 px-5 pb-3">
          {proposal.assumptions.map((a, i) => (
            <div key={i} className="font-mono text-[15px] text-fog-400">
              &middot; {a}
            </div>
          ))}
        </div>
      )}

      {check?.violations?.length > 0 && (
        <div className="space-y-1 px-5 pb-3">
          {check.violations.map((v) => (
            <div
              key={v.code}
              className={`flex items-start gap-1.5 font-mono text-[15px] ${
                v.severity === "block" ? "text-triage-immediate" : "text-signal-amber"
              }`}
            >
              <span>{v.severity === "block" ? "✕" : "!"}</span>
              <span>{v.message}</span>
            </div>
          ))}
        </div>
      )}

      {check?.fairness_note && (
        <div className="px-5 pb-3 font-mono text-[15px] text-signal-amber">
          &#9432; {check.fairness_note}
        </div>
      )}

      <div className="perforation mx-4" />

      <div className="flex items-center justify-between px-4 py-2.5">
        {decided ? (
          <span className="eyebrow">{proposal.status}</span>
        ) : (
          <>
            <button
              disabled={blocked || deciding}
              onClick={() => onDecide?.(proposal.mission_id, "approved")}
              className="flex items-center gap-1.5 rounded-lg bg-signal-cyan/15 px-3 py-1.5 text-xs font-medium text-signal-cyan transition hover:bg-signal-cyan/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <i className="ti ti-check" aria-hidden="true" />
              Approve
            </button>
            <button
              disabled={deciding}
              onClick={() => onDecide?.(proposal.mission_id, "modified")}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-fog-300 transition hover:bg-ink-700 disabled:opacity-40"
            >
              <i className="ti ti-edit" aria-hidden="true" />
              Modify
            </button>
            <button
              disabled={deciding}
              onClick={() => onDecide?.(proposal.mission_id, "rejected")}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-fog-400 transition hover:bg-triage-immediate/10 hover:text-triage-immediate disabled:opacity-40"
            >
              <i className="ti ti-x" aria-hidden="true" />
              Reject
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, dim }) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div className={`text-sm ${dim ? "text-fog-400 italic" : "text-fog-100"}`}>{value}</div>
    </div>
  );
}

function shortId(uuid) {
  return uuid ? uuid.toString().slice(0, 8) : "—";
}
