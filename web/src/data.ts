import { decodeCompactCandidates } from "./candidate-codec";
import {
  candidateFeatureSchema,
  featureCollectionSchema,
  layerSchema,
  manifestSchema,
  type CandidateFeature,
  type GenericFeatureCollection,
  type LoadedLayers,
  type Manifest,
} from "./types";

const textDecoder = new TextDecoder();
const validatedCandidates = new WeakMap<GenericFeatureCollection, CandidateFeature[]>();

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function fetchVerifiedJson(url: string, expectedSha256?: string): Promise<unknown> {
  const response = await fetch(url, { credentials: "same-origin", cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`Unable to load ${url}: HTTP ${response.status}`);
  }
  const bytes = await response.arrayBuffer();
  if (expectedSha256) {
    const actual = await sha256Hex(bytes);
    if (actual !== expectedSha256) {
      throw new Error(`Integrity check failed for ${url}`);
    }
  }
  return JSON.parse(textDecoder.decode(bytes)) as unknown;
}

export async function loadManifest(url = "./data/manifest.json"): Promise<Manifest> {
  return manifestSchema.parse(await fetchVerifiedJson(url));
}

export async function loadLayer(manifest: Manifest, layerId: string): Promise<GenericFeatureCollection> {
  const layer = layerSchema.parse(manifest.layers.find((item) => item.id === layerId));
  if (layer.id === "candidates" && manifest.compactCandidates) {
    const descriptor = manifest.compactCandidates;
    if (descriptor.sourceSha256 !== layer.sha256) throw new Error("Compact candidates do not match the source layer");
    const features = decodeCompactCandidates(await fetchVerifiedJson(descriptor.url, descriptor.sha256));
    if (features.length !== descriptor.featureCount) throw new Error("Compact candidate count mismatch");
    const collection: GenericFeatureCollection = { type: "FeatureCollection", features };
    validatedCandidates.set(collection, features);
    return collection;
  }
  const collection = featureCollectionSchema.parse(await fetchVerifiedJson(layer.url, layer.sha256));
  if (layer.id === "candidates") {
    validatedCandidates.set(collection, collection.features.map(feature => candidateFeatureSchema.parse(feature)));
  }
  return collection;
}

export async function loadDefaultLayers(manifest: Manifest): Promise<LoadedLayers> {
  const layers: LoadedLayers = {};
  await Promise.all(
    manifest.layers
      .filter((layer) => layer.defaultVisible || layer.id === "candidates")
      .map(async (layer) => {
        try {
          layers[layer.id] = await loadLayer(manifest, layer.id);
        } catch (error) {
          if (!layer.optional) throw error;
        }
      }),
  );
  return layers;
}

export function candidateFeatures(layers: LoadedLayers): CandidateFeature[] {
  if (!layers.candidates) return [];
  let candidates = validatedCandidates.get(layers.candidates);
  if (!candidates) {
    candidates = layers.candidates.features.map(feature => candidateFeatureSchema.parse(feature));
    validatedCandidates.set(layers.candidates, candidates);
  }
  return candidates;
}
