import { useMemo, useState } from "react";
import TriageCard from "./TriageCard.jsx";

export default function MissionQueue({ cards, onDecide, decidingId }) {
  const [filter, setFilter] = useState("all");

  const visible = useMemo(() => {
    const sorted = [...cards].sort((a, b) => b.proposal.priority_score - a.proposal.priority_score);
    if (filter === "pending")
      return sorted.filter((c) => ["proposed", "checked"].includes(c.proposal.status));
    if (filter === "blocked")
      return sorted.filter((c) => c.check?.violations?.some((v) => v.severity === "block"));
    return sorted;
  }, [cards, filter]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-1 pb-3">
        <span className="eyebrow">Mission queue</span>
        <div className="flex gap-1">
          {[
            ["all", "All"],
            ["pending", "Pending"],
            ["blocked", "Blocked"],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`rounded px-2.5 py-1 font-mono text-[15px] transition ${
                filter === key
                  ? "bg-signal-cyan/15 text-signal-cyan"
                  : "text-fog-400 hover:bg-ink-700 hover:text-fog-200"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {visible.map((card) => (
          <TriageCard
            key={card.proposal.mission_id}
            card={card}
            onDecide={onDecide}
            deciding={decidingId === card.proposal.mission_id}
          />
        ))}
        {visible.length === 0 && (
          <div className="rounded-xl border border-dashed border-ink-600 px-4 py-8 text-center text-sm text-fog-400">
            No missions in this view. Submit reports and run a cycle to generate proposals.
          </div>
        )}
      </div>
    </div>
  );
}
