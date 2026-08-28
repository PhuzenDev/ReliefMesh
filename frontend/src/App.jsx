import { useCallback, useEffect, useState } from "react";
import CycleToolbar from "./components/CommanderPanel/CycleToolbar.jsx";
import StatsBar from "./components/CommanderPanel/StatsBar.jsx";
import PipelineStrip from "./components/CommanderPanel/PipelineStrip.jsx";
import ModifyDecisionModal from "./components/CommanderPanel/ModifyDecisionModal.jsx";
import SituationMap from "./components/MapView/SituationMap.jsx";
import ReportIntakeForm from "./components/IncidentFeed/ReportIntakeForm.jsx";
import ReportFeed from "./components/IncidentFeed/ReportFeed.jsx";
import MissionQueue from "./components/MissionQueue/MissionQueue.jsx";
import { runCycle, replan, decideMission, getGeoState, actOnRoad } from "./api/client.js";
import { useMissionsSocket } from "./api/useMissionsSocket.js";
import { flushQueuedReports, loadQueuedReports } from "./offline/offlineQueue.js";

export default function App() {
  const { cards, setCards, connected, error: socketError } = useMissionsSocket();
  const [geoState, setGeoState] = useState(null);
  const [geoLoading, setGeoLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [decidingId, setDecidingId] = useState(null);
  const [modifyCard, setModifyCard] = useState(null);
  const [banner, setBanner] = useState(null);
  const [queuedCount, setQueuedCount] = useState(loadQueuedReports().length);
  const [rightTab, setRightTab] = useState("queue"); // "queue" | "report"
  const [poolSize, setPoolSize] = useState(0);
  const [cycleNumber, setCycleNumber] = useState(0);
  const [recentReports, setRecentReports] = useState([]);

  function pushRecentReports(entries) {
    setRecentReports((prev) => [...entries, ...prev].slice(0, 20));
  }

  const refreshGeo = useCallback(() => {
    setGeoLoading(true);
    getGeoState()
      .then(setGeoState)
      .catch((e) => setBanner({ kind: "error", message: e.message }))
      .finally(() => setGeoLoading(false));
  }, []);

  useEffect(() => {
    refreshGeo();
  }, [refreshGeo]);

  // Try flushing any offline-queued reports whenever the browser comes
  // back online.
  useEffect(() => {
    function handleOnline() {
      if (loadQueuedReports().length === 0) return;
      flushQueuedReports()
        .then(({ flushed, cards: newCards, reports }) => {
          if (flushed > 0) {
            setBanner({ kind: "ok", message: `Synced ${flushed} queued report(s)` });
            if (newCards) setCards(newCards);
            setQueuedCount(0);
            pushRecentReports(
              (reports ?? []).map((r, i) => ({
                id: `sync-${Date.now()}-${i}`,
                at: Date.now(),
                source: r.source,
                text: r.text,
                need_type: r.need_type,
                queued: false,
              }))
            );
          }
        })
        .catch((e) => setBanner({ kind: "error", message: `Offline sync failed: ${e.message}` }));
    }
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [setCards]);

  async function handleRunCycle() {
    setRunning(true);
    setBanner(null);
    try {
      const newCards = await runCycle();
      setCards(newCards);
      setCycleNumber((n) => n + 1);
      refreshGeo();
    } catch (e) {
      setBanner({ kind: "error", message: e.message });
    } finally {
      setRunning(false);
    }
  }

  async function handleReplan(reason) {
    setRunning(true);
    setBanner(null);
    try {
      const newCards = await replan(reason);
      setCards(newCards);
      setCycleNumber((n) => n + 1);
    } catch (e) {
      setBanner({ kind: "error", message: e.message });
    } finally {
      setRunning(false);
    }
  }

  async function handleDecide(missionId, decision) {
    if (decision === "modified") {
      const card = cards.find((c) => c.proposal.mission_id === missionId);
      setModifyCard(card);
      return;
    }
    setDecidingId(missionId);
    try {
      await decideMission(missionId, {
        mission_id: missionId,
        decision,
        decided_by: "commander-console",
      });
    } catch (e) {
      setBanner({ kind: "error", message: e.message });
    } finally {
      setDecidingId(null);
    }
  }

  async function handleModifySubmit(modifications) {
    const missionId = modifyCard.proposal.mission_id;
    setDecidingId(missionId);
    try {
      await decideMission(missionId, {
        mission_id: missionId,
        decision: "modified",
        modifications,
        decided_by: "commander-console",
      });
      setModifyCard(null);
    } catch (e) {
      setBanner({ kind: "error", message: e.message });
    } finally {
      setDecidingId(null);
    }
  }

  async function handleRoadAction(roadId, action) {
    try {
      await actOnRoad(roadId, action);
      refreshGeo();
      setBanner({ kind: "ok", message: `${roadId} marked ${action === "reopen" ? "open" : action}` });
    } catch (e) {
      setBanner({ kind: "error", message: e.message });
    }
  }

  function handleReportIngested(report, meta) {
    setQueuedCount(loadQueuedReports().length);
    if (meta?.poolSize != null) setPoolSize(meta.poolSize);
    pushRecentReports([
      {
        id: `submit-${Date.now()}`,
        at: Date.now(),
        source: report.source,
        text: report.text,
        need_type: report.need_type,
        queued: !!meta?.queued,
      },
    ]);
    setRightTab("queue");
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-4 border-b border-ink-700 bg-ink-800/80 px-6 py-5">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-signal-cyan/25 to-signal-cyan/5 ring-1 ring-signal-cyan/30">
          <span className="font-mono text-base font-bold tracking-tight text-signal-cyan">RM</span>
        </div>
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-fog-100">
            ReliefMesh
          </h1>
          <p className="eyebrow mt-1">Emergency response &amp; evidence fusion — commander console</p>
        </div>
        {queuedCount > 0 && (
          <div className="ml-auto flex items-center gap-2 rounded-lg border border-signal-amber/40 px-3.5 py-2">
            <span className="h-1.5 w-1.5 rounded-full bg-signal-amber" />
            <span className="text-xs font-medium text-signal-amber">
              {queuedCount} report(s) queued offline
            </span>
          </div>
        )}
      </header>

      <CycleToolbar
        onRunCycle={handleRunCycle}
        onReplan={handleReplan}
        running={running}
        connected={connected}
      />

      <PipelineStrip poolSize={poolSize} cards={cards} cycleNumber={cycleNumber} running={running} />

      <StatsBar cards={cards} geoState={geoState} />

      {(banner || socketError) && (
        <div
          className={`mx-4 mb-3 rounded border px-3 py-2 font-mono text-[15px] ${
            banner?.kind === "ok"
              ? "border-triage-minor/30 bg-triage-minor/10 text-triage-minor"
              : "border-triage-immediate/30 bg-triage-immediate/10 text-triage-immediate"
          }`}
        >
          {banner?.message ?? socketError}
        </div>
      )}

      <main className="grid flex-1 grid-cols-1 gap-4 overflow-hidden px-4 pb-4 lg:grid-cols-[1.4fr_1fr]">
        <SituationMap geoState={geoState} loading={geoLoading} onRoadAction={handleRoadAction} />

        <div className="flex min-h-0 flex-col rounded-xl border border-ink-700 bg-ink-800/30">
          <div className="flex border-b border-ink-700 px-2 pt-2">
            {[
              ["queue", "Mission queue"],
              ["report", "New report"],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => setRightTab(key)}
                className={`rounded-t px-3 py-2 font-mono text-[15px] uppercase tracking-wide transition ${
                  rightTab === key
                    ? "border-b-2 border-signal-cyan text-signal-cyan"
                    : "border-b-2 border-transparent text-fog-400 hover:text-fog-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {rightTab === "queue" ? (
              <MissionQueue cards={cards} onDecide={handleDecide} decidingId={decidingId} />
            ) : (
              <ReportIntakeForm onIngested={handleReportIngested} />
            )}
          </div>
        </div>
      </main>

      <ReportFeed reports={recentReports} />

      {modifyCard && (
        <ModifyDecisionModal
          card={modifyCard}
          submitting={decidingId === modifyCard.proposal.mission_id}
          onCancel={() => setModifyCard(null)}
          onSubmit={handleModifySubmit}
        />
      )}
    </div>
  );
}
