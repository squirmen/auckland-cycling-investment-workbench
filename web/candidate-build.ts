import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { z } from "zod";
import { COMPACT_CANDIDATE_FORMAT, encodeCompactCandidates } from "./src/candidate-codec";
import { layerSchema } from "./src/types";

/** Add a checked compact representation to a built site only, retaining canonical GeoJSON. */
export function manifestWithCompactCandidates(directory: string, manifestJson: string): string {
  const manifest = z.object({ layers: z.array(z.object({ id: z.string() }).passthrough()) }).passthrough().parse(JSON.parse(manifestJson));
  delete manifest.compactCandidates;
  const descriptor = manifest.layers.find(layer => layer.id === "candidates");
  if (!descriptor) return JSON.stringify(manifest, null, 2) + "\n";
  const source = layerSchema.parse(descriptor);
  if (source.url !== "./data/candidates.geojson") throw new Error("Unexpected canonical candidate URL");
  const bytes = readFileSync(join(directory, "candidates.geojson"));
  if (createHash("sha256").update(bytes).digest("hex") !== source.sha256) throw new Error("Canonical candidate checksum mismatch");
  const collection = z.object({ type: z.literal("FeatureCollection"), features: z.array(z.unknown()) }).parse(JSON.parse(bytes.toString("utf8")));
  const compact = JSON.stringify(encodeCompactCandidates(collection.features));
  writeFileSync(join(directory, "candidates.compact.json"), compact);
  manifest.compactCandidates = {
    format: COMPACT_CANDIDATE_FORMAT, url: "./data/candidates.compact.json",
    sha256: createHash("sha256").update(compact).digest("hex"), sourceSha256: source.sha256,
    featureCount: collection.features.length,
  };
  return JSON.stringify(manifest, null, 2) + "\n";
}
