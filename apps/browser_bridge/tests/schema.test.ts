import { describe, expect, it } from "vitest";
import {
  ALLOWED_ORIGINS,
  CHANNEL,
  MAX_PAYLOAD_BYTES,
  isCapturedFrame,
  redactText,
} from "../src/schema";

describe("bridge validation", () => {
  const allowedOrigin = [...ALLOWED_ORIGINS][0] ?? "";
  const frame = {
    channel: CHANNEL,
    frameType: "websocket-text",
    receivedAt: "2026-07-23T14:30:01Z",
    payload: '{"symbol":"EURUSD"}',
  };

  it("accepts the exact origin and schema", () => {
    expect(isCapturedFrame(frame, allowedOrigin)).toBe(true);
  });

  it("rejects the wrong origin", () => {
    expect(isCapturedFrame(frame, "https://evil.example")).toBe(false);
  });

  it("rejects oversized payloads", () => {
    expect(
      isCapturedFrame({ ...frame, payload: "x".repeat(MAX_PAYLOAD_BYTES + 1) }, allowedOrigin),
    ).toBe(false);
  });

  it("redacts bearer and query tokens", () => {
    expect(redactText("Bearer abc.def?token=secret&x=1")).not.toContain("secret");
    expect(redactText("Bearer abc.def?token=secret&x=1")).not.toContain("abc.def");
  });
});
