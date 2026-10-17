import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite + React. The dev server proxies API calls to the FastAPI backend so the
// dashboard can read the status/timeline endpoints without CORS config.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.js"],
    css: false,
  },
});
