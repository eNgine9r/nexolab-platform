import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("../../src", import.meta.url)),
    },
  },
  build: {
    outDir: "/tmp/nexolab-chart-benchmark-baseline",
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
    rollupOptions: { input: fileURLToPath(new URL("./baseline.html", import.meta.url)) },
  },
});
