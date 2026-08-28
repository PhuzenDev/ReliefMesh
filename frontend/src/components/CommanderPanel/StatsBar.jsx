function countBy(cards, predicate) {
  return cards.reduce((n, c) => (predicate(c) ? n + 1 : n), 0);
}

export default function StatsBar({ cards, geoState }) {
  const immediate = countBy(cards, (c) => c.proposal.priority_score >= 0.75);
  const pending = countBy(cards, (c) =>
    ["proposed", "checked"].includes(c.proposal.status)
  );
  const blocked = countBy(cards, (c) =>
    c.check?.violations?.some((v) => v.severity === "block")
  );

  const roadStatus = geoState?.road_status ?? {};
  const roadsBlocked = Object.values(roadStatus).filter((s) => s === "blocked").length;

  const shelters = Object.values(geoState?.shelters ?? {});
  const sheltersFull = shelters.filter(
    (s) => s.capacity > 0 && s.occupied / s.capacity >= 0.9
  ).length;

  const stats = [
    { label: "Immediate missions", value: immediate, tone: "text-triage-immediate", icon: "ti-alert-triangle" },
    { label: "Pending decisions", value: pending, tone: "text-signal-cyan", icon: "ti-hourglass" },
    { label: "Constraint-blocked", value: blocked, tone: "text-signal-amber", icon: "ti-ban" },
    { label: "Roads blocked", value: roadsBlocked, tone: "text-triage-immediate", icon: "ti-road-off" },
    { label: "Shelters near capacity", value: sheltersFull, tone: "text-signal-amber", icon: "ti-home-bolt" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 px-4 pb-4 pt-1 sm:grid-cols-3 lg:grid-cols-5">
      {stats.map((s) => (
        <div
          key={s.label}
          className="flex items-center gap-3.5 rounded-xl border border-ink-700 bg-ink-800/50 px-4 py-3.5"
        >
          <i className={`ti ${s.icon} text-xl ${s.tone}`} aria-hidden="true" />
          <div>
            <div className={`font-mono text-3xl font-semibold leading-none ${s.tone}`}>{s.value}</div>
            <div className="eyebrow mt-1.5">{s.label}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
