import { chmodSync, copyFileSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import { manifestWithJourneyReport } from "./report-integrity";
import { manifestWithCompactCandidates } from "./candidate-build";

const methodologySource = fileURLToPath(
  new URL("../documentation/methodology/methodology.md", import.meta.url),
);
const documents = {
  "methodology.md": methodologySource,
  "effective-network.md": fileURLToPath(new URL("../documentation/research/span-effective-network.md", import.meta.url)),
};
// STAND's `make publish` writes the site's /parking/ folder here: index.html, and STAND itself in uoa/.
const parkingSite = fileURLToPath(new URL("../parking/build/site", import.meta.url));
const standPage = fileURLToPath(new URL("../parking/build/site/uoa/index.html", import.meta.url));

export default defineConfig({
  base: "./",
  build: {
    rollupOptions: { input: { main: "index.html", research: "research.html" } },
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
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          if (request.url?.split("?")[0] === "/data/manifest.json") {
            try {
              response.setHeader("Content-Type", "application/json");
              response.setHeader("Cache-Control", "no-cache");
              response.end(manifestWithJourneyReport("public/data"));
            } catch (error) {
              response.statusCode = 500;
              response.end(error instanceof Error ? error.message : "Invalid journey report");
            }
            return;
          }
          const name = request.url?.split("?")[0]?.replace(/^\/documentation\//, "");
          if (!name || !(name in documents) || !request.url?.startsWith("/documentation/")) return next();
          response.setHeader("Content-Type", "text/plain; charset=utf-8");
          response.end(readFileSync(documents[name as keyof typeof documents]));
        });
      },
      closeBundle() {
        if (existsSync("dist/data/manifest.json")) {
          writeFileSync("dist/data/manifest.json", manifestWithCompactCandidates("dist/data", manifestWithJourneyReport("dist/data")));
        }
        mkdirSync("dist/documentation", { recursive: true });
        for (const [name, source] of Object.entries(documents)) copyFileSync(source, `dist/documentation/${name}`);
        // Vite leaves dotfiles in public/ behind; the Apache settings travel with the site.
        copyFileSync("public/.htaccess", "dist/.htaccess");
        // The pipeline writes its data files readable by their owner only. A web server
        // must be able to read them, or every data request returns 403.
        if (existsSync("dist/data")) {
          for (const name of readdirSync("dist/data")) chmodSync(`dist/data/${name}`, 0o644);
        }
      },
    },
    {
      // STAND, the University of Auckland bike parking map, is served at /parking/uoa/.
      // SPAN builds without it when STAND has not been built.
      name: "bundle-parking",
      apply: "build",
      closeBundle() {
        if (!existsSync(standPage)) {
          this.info("no STAND build in ../parking/build/site, so dist has no parking folder");
          return;
        }
        // cpSync copies dotfiles too, so uoa/.htaccess travels with the map.
        cpSync(parkingSite, "dist/parking", { recursive: true });
        this.info("copied ../parking/build/site to dist/parking");
      },
    },
  ],
});
