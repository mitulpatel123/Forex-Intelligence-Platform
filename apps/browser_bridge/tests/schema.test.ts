import { describe, expect, it } from "vitest";
import {
  ALLOWED_ORIGINS,
  CHANNEL,
  MAX_PAYLOAD_BYTES,
  isCapturedFrame,
  isPairStatusFrame,
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

  it("accepts a bounded UTF-8 decoded binary frame", () => {
    expect(
      isCapturedFrame(
        { ...frame, frameType: "websocket-binary-utf8" },
        allowedOrigin,
      ),
    ).toBe(true);
  });

  it("accepts a visible EUR/USD quote frame", () => {
    expect(
      isCapturedFrame(
        {
          ...frame,
          frameType: "dom-visible-quote",
          payload: '{"instrument":"EURUSD","bid":"1.08542","ask":"1.08544"}',
        },
        allowedOrigin,
      ),
    ).toBe(true);
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

  it("redacts sensitive JSON fields in supervised discovery frames", () => {
    const redacted = redactText(
      '{"account":12345,"sessionId":"session-secret","bid":"1.13743"}',
    );
    expect(redacted).not.toContain("12345");
    expect(redacted).not.toContain("session-secret");
    expect(redacted).toContain("1.13743");
  });

  it("accepts only an exact four-pair observer status frame", () => {
    const pairs = Object.fromEntries(
      ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"].map((instrument) => [
        instrument,
        { status: "READY", lastObservationAt: "2026-07-23T14:30:01Z" },
      ]),
    );
    const statusFrame = {
      channel: CHANNEL,
      frameType: "observer-pair-status",
      receivedAt: "2026-07-23T14:30:01Z",
      pairs,
    };
    expect(isPairStatusFrame(statusFrame, allowedOrigin)).toBe(true);
    expect(
      isPairStatusFrame(
        { ...statusFrame, pairs: { ...pairs, XAUUSD: pairs.EURUSD } },
        allowedOrigin,
      ),
    ).toBe(false);
    expect(
      isPairStatusFrame(
        {
          ...statusFrame,
          pairs: {
            ...pairs,
            USDJPY: { status: "READY", lastObservationAt: "not-a-time" },
          },
        },
        allowedOrigin,
      ),
    ).toBe(false);
  });
});
