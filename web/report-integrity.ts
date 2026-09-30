import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { z } from "zod";

const digest = z.string().regex(/^[a-f0-9]{64}$/);
const manifestHeader = z.object({
  runId: z.string(),
  effectiveNetwork: z.object({ topologySha256: digest }).passthrough().optional(),
}).passthrough();
const reportHeader = z.object({
  runId: z.string(), sourceHashes: z.object({ topology: digest }),
});

/** Bind exact report bytes at build/dev time; never modify source model results. */
export function manifestWithJourneyReport(directory: string): string {
  const manifest = manifestHeader.parse(JSON.parse(readFileSync(join(directory, "manifest.json"), "utf8")));
  delete manifest.journeyReport;
  const reportPath = join(directory, "access-experiment.json");
  if (existsSync(reportPath)) {
    const bytes = readFileSync(reportPath);
    const report = reportHeader.parse(JSON.parse(bytes.toString("utf8")));
    if (report.runId !== manifest.runId ||
      (manifest.effectiveNetwork && report.sourceHashes.topology !== manifest.effectiveNetwork.topologySha256)) {
      throw new Error("Journey report does not match the release run/topology");
    }
    manifest.journeyReport = {
      url: "./data/access-experiment.json",
      sha256: createHash("sha256").update(bytes).digest("hex"),
      runId: report.runId,
      topologySha256: report.sourceHashes.topology,
    };
  }
  return JSON.stringify(manifest, null, 2) + "\n";
}
