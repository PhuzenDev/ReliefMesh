import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_API_BASE (e.g. http://localhost:8000) picked up in src/api/client.js.
// Left unset in dev, requests go through this proxy to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/health": "http://localhost:8000",
      "/reports": "http://localhost:8000",
      "/cycle": "http://localhost:8000",
      "/missions": "http://localhost:8000",
      "/offline": "http://localhost:8000",
      "/geo": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
