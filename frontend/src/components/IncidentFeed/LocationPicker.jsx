import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, Marker, useMapEvents, useMap } from "react-leaflet";
import L from "leaflet";

// Same free, no-key OSM raster tiles SituationMap uses.
const OSM_TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSM_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// Default view before anything is picked — same fallback SituationMap uses.
const DEFAULT_CENTER = [12.6141, 80.1918];

// Nominatim (OSM's free geocoder, no API key). Usage policy caps this at
// ~1 req/sec and asks for a real User-Agent/Referer — browsers send a
// Referer automatically, which covers casual/dev use. If this ever needs
// to handle real traffic, proxy these two calls through the backend
// instead of hitting nominatim.openstreetmap.org straight from the client.
const NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search";
const NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse";

function pinIcon() {
  return L.divIcon({
    className: "",
    html: `
      <div style="position:relative;width:22px;height:30px;transform:translate(-1px,-2px);">
        <svg width="22" height="30" viewBox="0 0 22 30" xmlns="http://www.w3.org/2000/svg">
          <path d="M11 0C4.9 0 0 4.9 0 11c0 8.3 11 19 11 19s11-10.7 11-19c0-6.1-4.9-11-11-11z"
                fill="#4FB4C7" fill-opacity="0.9" stroke="#0D1216" stroke-width="1"/>
          <circle cx="11" cy="11" r="4" fill="#0D1216"/>
        </svg>
      </div>`,
    iconSize: [22, 30],
    iconAnchor: [11, 29],
  });
}

function FlyTo({ center, zoom }) {
  const map = useMap();
  useEffect(() => {
    if (center) map.flyTo(center, zoom ?? map.getZoom(), { duration: 0.6 });
  }, [map, center, zoom]);
  return null;
}

function ClickToPin({ onPick }) {
  useMapEvents({
    click(e) {
      onPick(e.latlng.lat, e.latlng.lng);
    },
  });
  return null;
}

export default function LocationPicker({ value, onChange, height = 200 }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [label, setLabel] = useState(null); // human-readable address for the pinned point
  const [flyTarget, setFlyTarget] = useState(null);
  const debounceRef = useRef(null);
  const reverseGeocodeRef = useRef(0); // ignore stale reverse-geocode responses

  const position = value?.lat != null && value?.lon != null ? [value.lat, value.lon] : null;

  // -- search-as-you-type -------------------------------------------------
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 3) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const url = `${NOMINATIM_SEARCH}?format=jsonv2&addressdetails=0&limit=5&q=${encodeURIComponent(query)}`;
        const res = await fetch(url);
        const data = await res.json();
        setResults(Array.isArray(data) ? data : []);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 350);
    return () => clearTimeout(debounceRef.current);
  }, [query]);

  async function reverseGeocode(lat, lon) {
    const requestId = ++reverseGeocodeRef.current;
    try {
      const url = `${NOMINATIM_REVERSE}?format=jsonv2&lat=${lat}&lon=${lon}`;
      const res = await fetch(url);
      const data = await res.json();
      if (requestId === reverseGeocodeRef.current) {
        setLabel(data?.display_name ?? null);
      }
    } catch {
      if (requestId === reverseGeocodeRef.current) setLabel(null);
    }
  }

  function pick(lat, lon, knownLabel) {
    onChange({ lat, lon });
    if (knownLabel) {
      setLabel(knownLabel);
    } else {
      setLabel(null);
      reverseGeocode(lat, lon);
    }
  }

  function selectResult(r) {
    const lat = parseFloat(r.lat);
    const lon = parseFloat(r.lon);
    pick(lat, lon, r.display_name);
    setFlyTarget([lat, lon]);
    setQuery("");
    setResults([]);
    setSearchOpen(false);
  }

  function useMyLocation() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      const { latitude, longitude } = pos.coords;
      pick(latitude, longitude);
      setFlyTarget([latitude, longitude]);
    });
  }

  const mapCenter = useMemo(() => position ?? DEFAULT_CENTER, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="col-span-2 flex flex-col gap-1.5 text-xs text-fog-300">
      <div className="flex items-center justify-between">
        <span>Location</span>
        <button
          type="button"
          onClick={useMyLocation}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[15px] text-signal-cyan transition hover:bg-signal-cyan/10"
        >
          <i className="ti ti-current-location" aria-hidden="true" />
          Use my location
        </button>
      </div>

      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSearchOpen(true);
          }}
          onFocus={() => setSearchOpen(true)}
          placeholder="Search an address or place…"
          className="w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-fog-100"
        />
        {searching && (
          <i
            className="ti ti-loader-2 absolute right-2 top-1/2 -translate-y-1/2 animate-spin text-fog-400"
            aria-hidden="true"
          />
        )}
        {searchOpen && results.length > 0 && (
          <ul className="absolute z-[500] mt-1 max-h-48 w-full overflow-auto rounded border border-ink-600 bg-ink-800 shadow-lg">
            {results.map((r) => (
              <li key={r.place_id}>
                <button
                  type="button"
                  onClick={() => selectResult(r)}
                  className="block w-full px-2 py-1.5 text-left text-xs text-fog-200 hover:bg-ink-700"
                >
                  {r.display_name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div
        className="overflow-hidden rounded border border-ink-600"
        style={{ height }}
        onClick={() => setSearchOpen(false)}
      >
        <MapContainer
          center={mapCenter}
          zoom={position ? 15 : 12}
          className="h-full w-full"
          zoomControl={false}
          attributionControl={true}
        >
          <TileLayer url={OSM_TILES} attribution={OSM_ATTRIBUTION} className="dark-tiles" maxZoom={19} />
          <ClickToPin onPick={(lat, lon) => pick(lat, lon)} />
          {flyTarget && <FlyTo center={flyTarget} zoom={15} />}
          {position && (
            <Marker
              position={position}
              icon={pinIcon()}
              draggable
              eventHandlers={{
                dragend: (e) => {
                  const { lat, lng } = e.target.getLatLng();
                  pick(lat, lng);
                },
              }}
            />
          )}
        </MapContainer>
      </div>

      <div className="flex items-center gap-1.5 font-mono text-[15px] text-fog-400">
        <i className="ti ti-map-pin" aria-hidden="true" />
        {position ? (
          <span className="truncate">{label ?? `${position[0].toFixed(5)}, ${position[1].toFixed(5)}`}</span>
        ) : (
          <span>Click the map, search above, or use your location</span>
        )}
      </div>
    </div>
  );
}
