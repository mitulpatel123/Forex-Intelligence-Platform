import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const manifest = JSON.parse(
  readFileSync(new URL("../manifest.json", import.meta.url), "utf8"),
) as {
  manifest_version: number;
  permissions: string[];
  host_permissions: string[];
  content_scripts: Array<{ matches: string[]; run_at: string; world?: string }>;
};

describe("manifest safety", () => {
  it("uses MV3 and no broad host access", () => {
    expect(manifest.manifest_version).toBe(3);
    expect(manifest.host_permissions).not.toContain("<all_urls>");
    expect(manifest.host_permissions.every((host) => host.startsWith("https://") || host === "http://127.0.0.1:8001/*")).toBe(true);
  });

  it("injects the observer in MAIN at document_start", () => {
    expect(manifest.content_scripts[0]).toMatchObject({
      run_at: "document_start",
      world: "MAIN",
    });
  });

  it("requests only extension-local storage", () => {
    expect(manifest.permissions).toEqual(["storage"]);
  });
});
