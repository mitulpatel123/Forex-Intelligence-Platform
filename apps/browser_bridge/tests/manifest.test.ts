import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const manifest = JSON.parse(
  readFileSync(new URL("../manifest.json", import.meta.url), "utf8"),
) as {
  manifest_version: number;
  permissions: string[];
  host_permissions: string[];
  content_scripts: Array<{
    matches: string[];
    run_at: string;
    all_frames?: boolean;
    world?: string;
  }>;
};
const serviceWorkerSource = readFileSync(
  new URL("../src/service-worker.ts", import.meta.url),
  "utf8",
);
const pageObserverSource = readFileSync(
  new URL("../src/page-observer.ts", import.meta.url),
  "utf8",
);

describe("manifest safety", () => {
  it("uses MV3 and no broad host access", () => {
    expect(manifest.manifest_version).toBe(3);
    expect(manifest.host_permissions).not.toContain("<all_urls>");
    expect(manifest.host_permissions.every((host) => host.startsWith("https://") || host === "http://127.0.0.1:8001/*")).toBe(true);
  });

  it("injects the observer in MAIN at document_start", () => {
    expect(manifest.content_scripts[0]).toMatchObject({
      run_at: "document_start",
      all_frames: true,
      world: "MAIN",
    });
  });

  it("injects both bridge scripts into the embedded trading terminal", () => {
    expect(manifest.content_scripts).toHaveLength(2);
    expect(manifest.content_scripts.every((script) => script.all_frames === true)).toBe(true);
  });

  it("requests only retry scheduling and extension-local storage", () => {
    expect(manifest.permissions).toEqual(["alarms", "storage"]);
  });

  it("returns the asynchronous message handler to keep MV3 delivery alive", () => {
    expect(serviceWorkerSource).toContain(
      "chrome.runtime.onMessage.addListener((message, sender) => handleMessage(message, sender));",
    );
    expect(serviceWorkerSource).not.toContain("void queueCapturedFrame");
    expect(serviceWorkerSource).not.toContain("lastSanitizedDiscoveryFrame: candidate.frame");
  });

  it("keeps WebSocket discovery disabled by default", () => {
    expect(pageObserverSource).toContain("let discoveryMode = false");
    expect(pageObserverSource).toContain("if (!discoveryMode) return");
    expect(serviceWorkerSource).toContain('discoveryMode: false');
  });
});
