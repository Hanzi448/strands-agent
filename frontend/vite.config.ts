import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  // `amazon-cognito-identity-js` pulls in the `buffer` Node polyfill, which
  // references the bare `global` at module-load time. Browsers have no
  // `global` (only `window`/`globalThis`), and unlike webpack/CRA, Vite does
  // not polyfill it -- so without this, the whole module graph throws
  // `ReferenceError: global is not defined` before React ever renders,
  // producing a blank page. Node-based checks (pytest, `npm run build`,
  // Vitest) never catch this because Node itself defines `global` natively.
  define: {
    global: "globalThis",
  },
});
