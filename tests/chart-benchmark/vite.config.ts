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
    outDir: "/tmp/nexolab-chart-benchmark-dist",
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
  },
});
