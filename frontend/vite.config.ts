import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The API base is read from VITE_API_BASE at build time; the dev proxy below
// keeps local development same-origin so no CORS round trips are needed.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8011",
        changeOrigin: true,
      },
    },
  },
});
