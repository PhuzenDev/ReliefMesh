export default function PipelineStrip({ poolSize, cards, cycleNumber, running }) {
  const clusterIds = new Set(cards.map((c) => c.proposal.cluster_id));
  const evidence = clusterIds.size;
  const planning = cards.length;
  const constraints = cards.filter((c) => c.check).length;
  const commander = cards.filter(
    (c) => !["proposed", "checked"].includes(c.proposal.status)
  ).length;

  const stages = [
    { label: "Reports", value: poolSize },
    { label: "Evidence", value: evidence },
    { label: "Planning", value: planning },
    { label: "Constraints", value: constraints },
    { label: "Commander", value: commander },
  ];

  return (
    <div className="mx-4 mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-ink-700 bg-ink-800/50 px-4 py-2.5">
      {stages.map((s, i) => (
        <span key={s.label} className="flex items-center gap-2">
          {i > 0 && <i className="ti ti-arrow-right text-fog-400" aria-hidden="true" />}
          <span className="text-[15px] font-medium text-fog-200">
            {s.label} <span className="text-signal-cyan">{s.value}</span>
          </span>
        </span>
      ))}

      <span className="ml-auto flex items-center gap-1.5 text-[14px] text-triage-minor">
        <i
          className={`ti ti-point-filled ${running ? "animate-pulse" : ""}`}
          aria-hidden="true"
        />
        Cycle {String(cycleNumber).padStart(3, "0")} {running ? "running" : "live"}
      </span>
    </div>
  );
}
