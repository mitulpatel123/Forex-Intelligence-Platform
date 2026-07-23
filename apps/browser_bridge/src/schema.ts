export const CHANNEL = "fip.icmarkets.discovery.v0.1";
export const CONFIG_CHANNEL = "fip.icmarkets.config.v0.1";
export const MAX_PAYLOAD_BYTES = 262_144;
export const ALLOWED_ORIGINS = new Set([
  "https://webtrader-sc.ic.com",
  "https://mt5web.icmarkets.com",
  "https://mt502web.icmarkets.com",
  "https://mt503web.icmarkets.com",
  "https://mt504web.icmarkets.com",
  "https://mt506web.icmarkets.com",
  "https://mt5demo.icmarkets.com",
]);

export type CapturedFrame = {
  channel: typeof CHANNEL;
  frameType: "websocket-text" | "websocket-binary-utf8" | "dom-visible-quote";
  receivedAt: string;
  payload: string;
};

export type PairStatusFrame = {
  channel: typeof CHANNEL;
  frameType: "observer-pair-status";
  receivedAt: string;
  pairs: Record<SupportedInstrument, PairObserverState>;
};

export function isCapturedFrame(value: unknown, origin: string): value is CapturedFrame {
  if (!ALLOWED_ORIGINS.has(origin) || typeof value !== "object" || value === null) return false;
  const frame = value as Record<string, unknown>;
  return (
    frame.channel === CHANNEL &&
    (frame.frameType === "websocket-text" ||
      frame.frameType === "websocket-binary-utf8" ||
      frame.frameType === "dom-visible-quote") &&
    typeof frame.receivedAt === "string" &&
    !Number.isNaN(Date.parse(frame.receivedAt)) &&
    typeof frame.payload === "string" &&
    new TextEncoder().encode(frame.payload).byteLength <= MAX_PAYLOAD_BYTES
  );
}

export function isPairStatusFrame(value: unknown, origin: string): value is PairStatusFrame {
  if (!ALLOWED_ORIGINS.has(origin) || typeof value !== "object" || value === null) return false;
  const frame = value as Record<string, unknown>;
  if (
    frame.channel !== CHANNEL ||
    frame.frameType !== "observer-pair-status" ||
    typeof frame.receivedAt !== "string" ||
    typeof frame.pairs !== "object" ||
    frame.pairs === null
  ) {
    return false;
  }
  const pairs = frame.pairs as Record<string, unknown>;
  return (
    Object.keys(pairs).length === SUPPORTED_INSTRUMENTS.length &&
    SUPPORTED_INSTRUMENTS.every((instrument) => {
    const state = pairs[instrument];
    return (
      typeof state === "object" &&
      state !== null &&
      ["FOUND", "READY", "MISSING", "AMBIGUOUS", "STALE"].includes(
        String((state as Record<string, unknown>).status),
      ) &&
      (((state as Record<string, unknown>).lastObservationAt === null) ||
        (typeof (state as Record<string, unknown>).lastObservationAt === "string" &&
          !Number.isNaN(
            Date.parse(String((state as Record<string, unknown>).lastObservationAt)),
          )))
    );
    })
  );
}

export function redactText(value: string): string {
  return value
    .replace(/bearer\s+[a-z0-9._~+/=-]+/gi, "Bearer [REDACTED]")
    .replace(/([?&](?:token|access_token|auth|session)=)[^&\s]+/gi, "$1[REDACTED]")
    .replace(
      /("(?:authorization|cookie|token|access_?token|refresh_?token|password|passwd|secret|mfa|otp|account|login|session_?id|balance|profile)"\s*:\s*)("(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|true|false|null)/gi,
      '$1"[REDACTED]"',
    );
}

export function isSupportedPairCandidate(value: string): boolean {
  return /(?:EUR|GBP|AUD)\s*[/_-]?\s*USD|USD\s*[/_-]?\s*JPY/i.test(value);
}
import type { PairObserverState } from "./dom-observer";
import {
  SUPPORTED_INSTRUMENTS,
  type SupportedInstrument,
} from "./instruments.generated";
