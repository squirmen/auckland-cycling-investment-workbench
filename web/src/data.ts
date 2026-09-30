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
const ATTEMPTS = 3;
let retryDelayMs = 1500;

/** Tests shorten the wait between attempts. */
export function setRetryDelayMs(value: number): void {
  retryDelayMs = value;
}

/** Share of a download received so far, from 0 to 1. Only reported when the size is known. */
export type Progress = (share: number) => void;

/** A dropped connection or a busy server is worth another try; a missing file is not. */
class TransientError extends Error {}

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function readBody(response: Response, onProgress?: Progress, totalBytes?: number): Promise<ArrayBuffer> {
  if (!onProgress || !totalBytes || !response.body) return response.arrayBuffer();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.byteLength;
    onProgress(Math.min(1, received / totalBytes));
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes.buffer;
}

async function fetchBytes(url: string, onProgress?: Progress, totalBytes?: number): Promise<ArrayBuffer> {
  let response: Response;
  try {
    response = await fetch(url, { credentials: "same-origin", cache: "no-cache" });
  } catch {
    throw new TransientError(`Unable to load ${url}: the connection failed`);
  }
  if (!response.ok) {
    const message = `Unable to load ${url}: HTTP ${response.status}`;
    throw response.status >= 500 || response.status === 408 || response.status === 429 ? new TransientError(message) : new Error(message);
  }
  try {
    return await readBody(response, onProgress, totalBytes);
  } catch {
    throw new TransientError(`Unable to load ${url}: the connection dropped`);
  }
}

/** Fetch a file, trying again after a dropped connection, and check its bytes before parsing. */
export async function fetchVerifiedJson(url: string, expectedSha256?: string, onProgress?: Progress, totalBytes?: number): Promise<unknown> {
  let bytes: ArrayBuffer | undefined;
  for (let attempt = 1; bytes === undefined; attempt += 1) {
    try {
      bytes = await fetchBytes(url, onProgress, totalBytes);
    } catch (error) {
      if (!(error instanceof TransientError) || attempt >= ATTEMPTS) throw error;
      await new Promise((resolve) => setTimeout(resolve, attempt * retryDelayMs));
    }
  }
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

export async function loadLayer(manifest: Manifest, layerId: string, onProgress?: Progress): Promise<GenericFeatureCollection> {
  const layer = layerSchema.parse(manifest.layers.find((item) => item.id === layerId));
  if (layer.id === "candidates" && manifest.compactCandidates) {
    const descriptor = manifest.compactCandidates;
    if (descriptor.sourceSha256 !== layer.sha256) throw new Error("Compact candidates do not match the source layer");
    const features = decodeCompactCandidates(await fetchVerifiedJson(descriptor.url, descriptor.sha256, onProgress, descriptor.bytes));
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

/** The links the opening views need: every build order and every best-value link. */
export async function loadInitialCandidates(manifest: Manifest, onProgress?: Progress): Promise<GenericFeatureCollection> {
  const descriptor = manifest.initialCandidates;
  if (!descriptor) return loadLayer(manifest, "candidates", onProgress);
  const source = manifest.layers.find(layer => layer.id === "candidates");
  if (descriptor.sourceSha256 !== source?.sha256) throw new Error("Initial candidates do not match the source layer");
  const features = decodeCompactCandidates(await fetchVerifiedJson(descriptor.url, descriptor.sha256, onProgress, descriptor.bytes));
  const ids = new Set(features.map(feature => feature.properties.candidateId));
  if (features.length !== descriptor.featureCount || ids.size !== features.length) throw new Error("Initial candidate count mismatch");
  for (const purposes of Object.values(manifest.portfolios)) for (const steps of Object.values(purposes)) {
    if (steps.some(step => !ids.has(step.candidateId))) throw new Error("Initial candidates omit a build-order link");
  }
  const collection: GenericFeatureCollection = { type: "FeatureCollection", features };
  validatedCandidates.set(collection, features);
  return collection;
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
