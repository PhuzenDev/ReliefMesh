const SOURCE_LABEL = {
  call: "CALL",
  sms: "SMS",
  field_team: "FIELD",
  sensor: "SENSOR",
};

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default function ReportFeed({ reports }) {
  return (
    <div className="mx-4 mb-4 rounded-xl border border-ink-700 bg-ink-800/50 px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="eyebrow">Live report feed</span>
        <span className="font-mono text-[15px] text-fog-400">
          {reports.length} this session
        </span>
      </div>

      {reports.length === 0 ? (
        <div className="py-3 text-sm text-fog-400">
          No reports yet — submitted intake shows up here as it arrives.
        </div>
      ) : (
        <div className="flex gap-0 overflow-x-auto">
          {reports.map((r, i) => (
            <div
              key={r.id}
              className={`min-w-[200px] max-w-[220px] shrink-0 px-3.5 py-1 ${
                i > 0 ? "border-l border-ink-700" : ""
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[15px] text-signal-cyan">
                  {SOURCE_LABEL[r.source] ?? r.source.toUpperCase()}
                  {r.queued && <i className="ti ti-clock-pause ml-1 text-signal-amber" aria-hidden="true" />}
                </span>
                <span className="font-mono text-[15px] text-fog-400">{formatTime(r.at)}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-[15px] text-fog-100">
                {r.text || `${r.need_type.replace("_", " / ")} report`}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
