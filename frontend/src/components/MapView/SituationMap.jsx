import { useEffect, useMemo, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Polyline,
  Circle,
  Marker,
  Popup,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import { roadGraphNodes, roadGraphEdges } from "../../data/roadGraphFixture.js";

const ROAD_COLOR = {
  open: "#4FA876",
  degraded: "#E8B23D",
  blocked: "#D9463C",
};

// Free, no-API-key raster tiles (CARTO's dark basemap now requires an
// account/key). Standard OSM tiles are light, so we flip them dark with a
// CSS filter (applied via the "dark-tiles" className below) rather than
// paying for a hosted dark-theme tile provider.
const OSM_TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function shelterIcon(pct) {
  const fillHeight = Math.round(14 * Math.min(1, Math.max(0, pct)));
  return L.divIcon({
    className: "",
    html: `
      <div style="position:relative;width:16px;height:16px;">
        <div style="position:absolute;inset:0;background:#171E24;border:1.5px solid #4FB4C7;border-radius:2px;"></div>
        <div style="position:absolute;left:0;right:0;bottom:0;height:${fillHeight}px;background:#4FB4C7;opacity:0.55;border-radius:0 0 1px 1px;"></div>
      </div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

// Keeps the map framed on whatever geometry we actually have (road graph
// nodes) — recomputed once on mount, not on every render.
function FitToData({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [24, 24] });
  }, [map, bounds]);
  return null;
}

function RoadPopupActions({ roadId, status, onAction }) {
  const [pending, setPending] = useState(null);

  async function run(action) {
    setPending(action);
    try {
      await onAction(roadId, action);
    } finally {
      setPending(null);
    }
  }

  const options = [
    { key: "reopen", label: "Reopen", icon: "ti-check", disabled: status === "open" },
    { key: "degrade", label: "Degrade", icon: "ti-alert-triangle", disabled: status === "degraded" },
    { key: "block", label: "Block", icon: "ti-ban", disabled: status === "blocked" },
  ];

  return (
    <div className="min-w-[170px] font-body">
      <div className="mb-1 font-mono text-[15px] uppercase tracking-wide text-fog-300">
        {roadId}
      </div>
      <div className="mb-2 flex items-center gap-1.5 text-xs" style={{ color: ROAD_COLOR[status] }}>
        <i className="ti ti-point-filled" aria-hidden="true" />
        Status: {status}
      </div>
      <div className="flex gap-1">
        {options.map((o) => (
          <button
            key={o.key}
            disabled={o.disabled || pending !== null}
            onClick={() => run(o.key)}
            className="flex items-center gap-1 rounded-lg border border-ink-600 px-2 py-1 text-[15px] font-medium text-fog-100 transition hover:bg-ink-700 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <i className={`ti ${pending === o.key ? "ti-loader-2 animate-spin" : o.icon}`} aria-hidden="true" />
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function SituationMap({ geoState, loading, onRoadAction }) {
  const roadStatus = geoState?.road_status ?? {};
  const hazardZones = geoState?.hazard_zones ?? [];
  const shelters = Object.values(geoState?.shelters ?? {});

  const bounds = useMemo(() => {
    const pts = Object.values(roadGraphNodes).map((n) => [n.lat, n.lon]);
    if (pts.length === 0) return null;
    return L.latLngBounds(pts);
  }, []);

  const center = bounds ? bounds.getCenter() : [12.6141, 80.1918];

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-800/50">
      <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
        <span className="eyebrow">Situation map</span>
        <div className="flex items-center gap-4 font-mono text-[15px] text-fog-300">
          <Legend swatch={ROAD_COLOR.open} label="Open" />
          <Legend swatch={ROAD_COLOR.degraded} label="Degraded" />
          <Legend swatch={ROAD_COLOR.blocked} label="Blocked" />
        </div>
      </div>

      <div className="relative flex-1">
        {loading ? (
          <div className="flex h-full items-center justify-center text-sm text-fog-400">
            Loading geo state…
          </div>
        ) : (
          <MapContainer
            center={center}
            zoom={14}
            className="h-full w-full"
            zoomControl={true}
            attributionControl={true}
          >
            <TileLayer url={OSM_TILES} attribution={OSM_ATTRIBUTION} className="dark-tiles" maxZoom={19} />
            {bounds && <FitToData bounds={bounds} />}

            {hazardZones.map((hz, i) => (
              <Circle
                key={i}
                center={[hz.lat, hz.lon]}
                radius={hz.radius_km * 1000}
                pathOptions={{
                  color: "#D9463C",
                  weight: 1,
                  fillColor: "#D9463C",
                  fillOpacity: 0.15 + hz.risk * 0.25,
                }}
              >
                <Popup>
                  <div className="font-mono text-[15px]">
                    Hazard zone &middot; risk {(hz.risk * 100).toFixed(0)}%
                    <br />
                    radius {hz.radius_km} km
                  </div>
                </Popup>
              </Circle>
            ))}

            {roadGraphEdges.map((edge) => {
              const from = roadGraphNodes[edge.from];
              const to = roadGraphNodes[edge.to];
              if (!from || !to) return null;
              const status = roadStatus[edge.id] ?? "open";
              return (
                <Polyline
                  key={edge.id}
                  positions={[
                    [from.lat, from.lon],
                    [to.lat, to.lon],
                  ]}
                  pathOptions={{
                    color: ROAD_COLOR[status],
                    weight: status === "blocked" ? 4 : 3,
                    dashArray: status === "blocked" ? "6 6" : undefined,
                    opacity: 0.9,
                  }}
                  eventHandlers={{
                    mouseover: (e) => e.target.setStyle({ weight: 6 }),
                    mouseout: (e) =>
                      e.target.setStyle({ weight: status === "blocked" ? 4 : 3 }),
                  }}
                >
                  <Popup>
                    <RoadPopupActions roadId={edge.id} status={status} onAction={onRoadAction} />
                  </Popup>
                </Polyline>
              );
            })}

            {shelters.map((s) => {
              const pct = s.capacity > 0 ? s.occupied / s.capacity : 0;
              return (
                <Marker key={s.shelter_id} position={[s.lat, s.lon]} icon={shelterIcon(pct)}>
                  <Popup>
                    <div className="font-mono text-[15px]">
                      <div className="mb-1 font-semibold">{s.shelter_id}</div>
                      {s.occupied} / {s.capacity} occupied ({Math.round(pct * 100)}%)
                    </div>
                  </Popup>
                </Marker>
              );
            })}
          </MapContainer>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-ink-700 px-4 py-2 font-mono text-[15px] text-fog-400">
        {Object.entries(roadStatus).map(([id, status]) => (
          <span key={id} className="flex items-center gap-1.5">
            <i className="ti ti-point-filled" style={{ color: ROAD_COLOR[status] }} aria-hidden="true" />
            {id}
          </span>
        ))}
      </div>
    </div>
  );
}

function Legend({ swatch, label }) {
  return (
    <span className="flex items-center gap-1.5">
      <i className="ti ti-point-filled" style={{ color: swatch }} aria-hidden="true" />
      {label}
    </span>
  );
}
