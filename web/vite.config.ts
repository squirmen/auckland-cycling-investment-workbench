import { chmodSync, copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

const methodologySource = fileURLToPath(
  new URL("../documentation/methodology/methodology.md", import.meta.url),
);
const documents = {
  "methodology.md": methodologySource,
  "effective-network.md": fileURLToPath(new URL("../documentation/research/span-effective-network.md", import.meta.url)),
};

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
          const name = request.url?.split("?")[0]?.replace(/^\/documentation\//, "");
          if (!name || !(name in documents) || !request.url?.startsWith("/documentation/")) return next();
          response.setHeader("Content-Type", "text/plain; charset=utf-8");
          response.end(readFileSync(documents[name as keyof typeof documents]));
        });
      },
      closeBundle() {
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
  ],
});
