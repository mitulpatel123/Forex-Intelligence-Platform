import type { CapturedFrame } from "./schema";

export const DISCOVERY_INGEST_URL = "http://127.0.0.1:8001/ingest/discovery";
export const PROVIDER_INGEST_URL = "http://127.0.0.1:8001/ingest/provider";
export const HEARTBEAT_URL = "http://127.0.0.1:8001/ingest/bridge-heartbeat";

export type BrowserIdentity = {
  connectionId: string;
  sessionId: string;
};

export type VisibleQuote = {
  instrument: "EURUSD";
  bid: string;
  ask: string;
};

export function browserIdentity(
  browserRunId: string,
  tabId: number,
  frameId: number,
  documentSessionId: string,
): BrowserIdentity {
  return {
    connectionId: `browser-${browserRunId}-tab-${tabId}-frame-${frameId}`,
    sessionId: `document-${documentSessionId}`,
  };
}

export function parseVisibleQuote(frame: CapturedFrame): VisibleQuote | null {
  if (frame.frameType !== "dom-visible-quote") return null;
  let value: unknown;
  try {
    value = JSON.parse(frame.payload);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const quote = value as Record<string, unknown>;
  if (
    quote.instrument !== "EURUSD" ||
    typeof quote.bid !== "string" ||
    typeof quote.ask !== "string"
  ) {
    return null;
  }
  return { instrument: "EURUSD", bid: quote.bid, ask: quote.ask };
}

export function providerRequest(
  eventId: string,
  identity: BrowserIdentity,
  frame: CapturedFrame,
  quote: VisibleQuote,
): Record<string, unknown> {
  return {
    event_id: eventId,
    connection_id: identity.connectionId,
    session_id: identity.sessionId,
    received_at: frame.receivedAt,
    semantics: "snapshot",
    payload: {
      instrument: "EURUSD",
      bid: quote.bid,
      ask: quote.ask,
      provider_event_time: null,
      observation_source: "visible_dom",
      observation_level: "DISPLAY_QUOTE",
      is_provider_tick: false,
    },
    channel_metadata: {
      observation_event_id: eventId,
      capture_method: "visible_dom",
      observation_level: "DISPLAY_QUOTE",
      is_provider_tick: false,
      provider_transport: "wss_binary_arraybuffer",
      provider_timestamp_available: false,
    },
  };
}

export function discoveryRequest(
  eventId: string,
  identity: BrowserIdentity,
  frame: CapturedFrame,
): Record<string, unknown> {
  return {
    event_id: eventId,
    connection_id: identity.connectionId,
    session_id: identity.sessionId,
    frame,
  };
}
