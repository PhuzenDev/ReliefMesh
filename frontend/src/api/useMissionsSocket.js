import { useEffect, useRef, useState } from "react";
import { getMissions, missionsSocketUrl } from "./client.js";

// Subscribes to /ws/missions for live mission-card updates. Falls back to
// polling GET /missions every POLL_MS if the socket can't connect (e.g.
// backend running without websocket support behind a plain proxy).
const POLL_MS = 8000;

export function useMissionsSocket() {
  const [cards, setCards] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let ws;
    let cancelled = false;

    function startPolling() {
      if (pollRef.current) return;
      getMissions().then(setCards).catch((e) => setError(e.message));
      pollRef.current = setInterval(() => {
        getMissions().then(setCards).catch((e) => setError(e.message));
      }, POLL_MS);
    }

    try {
      ws = new WebSocket(missionsSocketUrl());
      ws.onopen = () => {
        if (cancelled) return;
        setConnected(true);
        setError(null);
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "missions_snapshot" || msg.type === "missions_update") {
          setCards(msg.cards ?? []);
        }
      };
      ws.onerror = () => {
        setConnected(false);
        startPolling();
      };
      ws.onclose = () => {
        setConnected(false);
        startPolling();
      };
    } catch (e) {
      setError(e.message);
      startPolling();
    }

    return () => {
      cancelled = true;
      ws?.close();
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  return { cards, setCards, connected, error };
}
