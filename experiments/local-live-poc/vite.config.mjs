import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// scripts/run-local.sh (the Sunday launcher) sets LOCAL_LIVE_FROZEN_UI=1. During a service, a file
// change in this checkout (another agent's edit, a branch switch, a sync client) must not hot-reload
// the operator page: the reload stops MediaRecorder and the microphone mid-sermon.
const frozenUi = process.env.LOCAL_LIVE_FROZEN_UI === "1";

export default defineConfig({
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
    ...(frozenUi ? { hmr: false, watch: null } : {}),
  },
  plugins: [react()],
});
