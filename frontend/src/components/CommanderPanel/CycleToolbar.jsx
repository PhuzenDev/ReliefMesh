export default function CycleToolbar({ onRunCycle, onReplan, running, connected }) {
  return (
    <div className="flex items-center gap-3 border-b border-ink-700 bg-ink-800/60 px-6 py-4">
      <div className="flex items-center gap-3">
        <button
          onClick={onRunCycle}
          disabled={running}
          className="flex items-center gap-2 rounded-xl bg-signal-cyan/15 px-4 py-2 text-sm font-semibold text-signal-cyan shadow-sm shadow-signal-cyan/10 transition hover:bg-signal-cyan/25 disabled:opacity-50"
        >
          <i className={`ti ${running ? "ti-loader-2 animate-spin" : "ti-player-play"}`} aria-hidden="true" />
          {running ? "Running…" : "Run cycle"}
        </button>
        <button
          onClick={() => onReplan("manual_replan")}
          disabled={running}
          className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium text-fog-300 transition hover:bg-ink-700 disabled:opacity-50"
        >
          <i className="ti ti-refresh" aria-hidden="true" />
          Replan
        </button>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <i
          className={`ti ti-point-filled ${connected ? "text-triage-minor animate-pulse" : "text-fog-400"}`}
          aria-hidden="true"
        />
        <span className="text-xs font-medium text-fog-300">
          {connected ? "Live" : "Reconnecting…"}
        </span>
      </div>
    </div>
  );
}
