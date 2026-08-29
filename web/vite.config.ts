import { copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

const methodologySource = fileURLToPath(
  new URL("../documentation/methodology/methodology.md", import.meta.url),
);

export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
    sourcemap: false,
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
    },
  },
  plugins: [
    {
      name: "bundle-methodology",
      closeBundle() {
        mkdirSync("dist/documentation", { recursive: true });
        copyFileSync(methodologySource, "dist/documentation/methodology.md");
      },
    },
  ],
});
