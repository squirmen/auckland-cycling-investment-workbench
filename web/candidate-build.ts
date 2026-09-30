import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { z } from "zod";
import { COMPACT_CANDIDATE_FORMAT, decodeCompactCandidates, encodeCompactCandidates } from "./src/candidate-codec";
import { paretoFront } from "./src/model";
import { layerSchema, purposeIds, scenarioIds, type CandidateFeature } from "./src/types";

/** Include every budget's build order and every full-universe Pareto member.
 * A point dominated in the full universe remains dominated in this subset.
 */
export function initialCandidateIds(candidates: CandidateFeature[], portfolios: unknown): Set<string> {
  const sequences = z.record(z.record(z.array(z.object({ candidateId: z.string() })))).parse(portfolios);
  const ids = new Set<string>();
  for (const scenario of scenarioIds) for (const purpose of purposeIds) {
    const steps = sequences[scenario]?.[purpose];
    if (!steps) throw new Error("Initial candidates require all scenario/purpose portfolios");
    for (const step of steps) ids.add(step.candidateId);
    for (const id of paretoFront(candidates, scenario, purpose)) ids.add(id);
  }
  const known = new Set(candidates.map(f => f.properties.candidateId));
  if ([...ids].some(id => !known.has(id))) throw new Error("Portfolio references an unknown candidate");
  return ids;
}

/** Add a checked compact representation to a built site only, retaining canonical GeoJSON. */
export function manifestWithCompactCandidates(directory: string, manifestJson: string): string {
  const manifest = z.object({ layers: z.array(z.object({ id: z.string() }).passthrough()) }).passthrough().parse(JSON.parse(manifestJson));
  delete manifest.compactCandidates;
  delete manifest.initialCandidates;
  const descriptor = manifest.layers.find(layer => layer.id === "candidates");
  if (!descriptor) return JSON.stringify(manifest, null, 2) + "\n";
  const source = layerSchema.parse(descriptor);
  if (source.url !== "./data/candidates.geojson") throw new Error("Unexpected canonical candidate URL");
  const bytes = readFileSync(join(directory, "candidates.geojson"));
  if (createHash("sha256").update(bytes).digest("hex") !== source.sha256) throw new Error("Canonical candidate checksum mismatch");
  const collection = z.object({ type: z.literal("FeatureCollection"), features: z.array(z.unknown()) }).parse(JSON.parse(bytes.toString("utf8")));
  const packed = encodeCompactCandidates(collection.features);
  const compact = JSON.stringify(packed);
  writeFileSync(join(directory, "candidates.compact.json"), compact);
  manifest.compactCandidates = {
    format: COMPACT_CANDIDATE_FORMAT, url: "./data/candidates.compact.json",
    sha256: createHash("sha256").update(compact).digest("hex"), sourceSha256: source.sha256,
    featureCount: collection.features.length, bytes: Buffer.byteLength(compact),
  };
  if (manifest.portfolios) {
    const candidates = decodeCompactCandidates(packed);
    const ids = initialCandidateIds(candidates, manifest.portfolios);
    const initial = JSON.stringify(encodeCompactCandidates(candidates.filter(f => ids.has(f.properties.candidateId))));
    writeFileSync(join(directory, "candidates.initial.json"), initial);
    manifest.initialCandidates = {
      format: COMPACT_CANDIDATE_FORMAT, scope: "portfolios_and_frontiers_v1",
      url: "./data/candidates.initial.json", sha256: createHash("sha256").update(initial).digest("hex"),
      sourceSha256: source.sha256, featureCount: ids.size, bytes: Buffer.byteLength(initial),
    };
  }
  return JSON.stringify(manifest, null, 2) + "\n";
}
