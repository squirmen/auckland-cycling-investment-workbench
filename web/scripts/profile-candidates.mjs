// Local payload benchmark; no server or source files are changed.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { build } from "esbuild";

const mode = process.argv[2];
assert.ok(["canonical", "compact", "verify"].includes(mode), "Use canonical, compact or verify");
const root = path.resolve(import.meta.dirname, "..");
const bundle = await build({
  stdin: { contents: 'export {decodeCompactCandidates} from "./src/candidate-codec"; export {candidateFeatureSchema, featureCollectionSchema} from "./src/types";', resolveDir: root },
  bundle: true, platform: "node", format: "esm", write: false,
});
const { decodeCompactCandidates, candidateFeatureSchema, featureCollectionSchema } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
const source = path.join(root, "dist/data/candidates.geojson");
const compact = path.join(root, "dist/data/candidates.compact.json");
if (mode === "verify") {
  const original = JSON.parse(readFileSync(source, "utf8"));
  const decoded = decodeCompactCandidates(JSON.parse(readFileSync(compact, "utf8")));
  assert.equal(decoded.length, original.features.length);
  for (let i = 0; i < decoded.length; i++) assert.deepEqual(decoded[i], candidateFeatureSchema.parse(original.features[i]));
  process.stdout.write(JSON.stringify({ mode, featuresVerified: decoded.length, exactValidatedValues: true }) + "\n");
} else {
  const bytes = readFileSync(mode === "canonical" ? source : compact);
  const parseStart = performance.now();
  const data = JSON.parse(bytes.toString("utf8"));
  const parseMs = performance.now() - parseStart;
  const validationStart = performance.now();
  const features = mode === "compact" ? decodeCompactCandidates(data) : featureCollectionSchema.parse(data).features.map(f => candidateFeatureSchema.parse(f));
  const validationMs = performance.now() - validationStart;
  const peakRssKiB = process.resourceUsage().maxRSS;
  process.stdout.write(JSON.stringify({ mode, features: features.length, bytes: bytes.length,
    gzipBytes: gzipSync(bytes).length, sha256: createHash("sha256").update(bytes).digest("hex"),
    parseMs, validationMs, totalDecodeMs: parseMs + validationMs, peakRssKiB,
    runtime: process.version, platform: process.platform,
    note: "Single fresh Node process; excludes network, hashing, map rendering and gzip timing. Not a browser or mobile-device speed estimate." }) + "\n");
}
