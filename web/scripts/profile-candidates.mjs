// Local payload benchmark; no server or source files are changed.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { build } from "esbuild";

const mode = process.argv[2];
assert.ok(["canonical", "compact", "initial", "verify"].includes(mode), "Use canonical, compact, initial or verify");
const root = path.resolve(import.meta.dirname, "..");
const bundle = await build({
  stdin: { contents: 'export {decodeCompactCandidates} from "./src/candidate-codec"; export {candidateFeatureSchema, featureCollectionSchema, scenarioIds, purposeIds} from "./src/types"; export {paretoFront} from "./src/model";', resolveDir: root },
  bundle: true, platform: "node", format: "esm", write: false,
});
const { decodeCompactCandidates, candidateFeatureSchema, featureCollectionSchema, scenarioIds, purposeIds, paretoFront } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
const source = path.join(root, "dist/data/candidates.geojson");
const compact = path.join(root, "dist/data/candidates.compact.json");
const initialPath = path.join(root, "dist/data/candidates.initial.json");
if (mode === "verify") {
  const original = JSON.parse(readFileSync(source, "utf8"));
  const decoded = decodeCompactCandidates(JSON.parse(readFileSync(compact, "utf8")));
  assert.equal(decoded.length, original.features.length);
  for (let i = 0; i < decoded.length; i++) assert.deepEqual(decoded[i], candidateFeatureSchema.parse(original.features[i]));
  const initial = decodeCompactCandidates(JSON.parse(readFileSync(initialPath, "utf8")));
  const byId = new Map(decoded.map(f => [f.properties.candidateId, f]));
  for (const feature of initial) assert.deepEqual(feature, byId.get(feature.properties.candidateId));
  for (const s of scenarioIds) for (const p of purposeIds) assert.deepEqual(paretoFront(initial, s, p), paretoFront(decoded, s, p));
  const ids = new Set(initial.map(f => f.properties.candidateId));
  const manifest = JSON.parse(readFileSync(path.join(root, "dist/data/manifest.json"), "utf8"));
  for (const purposes of Object.values(manifest.portfolios)) for (const steps of Object.values(purposes)) for (const step of steps) assert.ok(ids.has(step.candidateId));
  process.stdout.write(JSON.stringify({ mode, featuresVerified: decoded.length, initialFeaturesVerified: initial.length, exactValidatedValues: true, allPortfoliosAndFrontiersPreserved: true }) + "\n");
} else {
  const bytes = readFileSync(mode === "canonical" ? source : mode === "initial" ? initialPath : compact);
  const parseStart = performance.now();
  const data = JSON.parse(bytes.toString("utf8"));
  const parseMs = performance.now() - parseStart;
  const validationStart = performance.now();
  const features = mode !== "canonical" ? decodeCompactCandidates(data) : featureCollectionSchema.parse(data).features.map(f => candidateFeatureSchema.parse(f));
  const validationMs = performance.now() - validationStart;
  const peakRssKiB = process.resourceUsage().maxRSS;
  process.stdout.write(JSON.stringify({ mode, features: features.length, bytes: bytes.length,
    gzipBytes: gzipSync(bytes).length, sha256: createHash("sha256").update(bytes).digest("hex"),
    parseMs, validationMs, totalDecodeMs: parseMs + validationMs, peakRssKiB,
    runtime: process.version, platform: process.platform,
    note: "Single fresh Node process; excludes network, hashing, map rendering and gzip timing. Not a browser or mobile-device speed estimate." }) + "\n");
}
