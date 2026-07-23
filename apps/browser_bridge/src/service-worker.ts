type BridgeState = "connected" | "disconnected" | "waiting for EUR/USD" | "receiving" | "error";

const INGEST_URL = "http://127.0.0.1:8001/ingest/discovery";
const PROVIDER_INGEST_URL = "http://127.0.0.1:8001/ingest/provider";
let state: BridgeState = "disconnected";
let attempt = 0;

async function setState(next: BridgeState): Promise<void> {
  state = next;
  await chrome.storage.local.set({ bridgeState: next });
}

function boundedBackoffMs(): number {
  const cap = Math.min(30_000, 500 * 2 ** attempt);
  attempt += 1;
  return Math.round(cap * (0.75 + Math.random() * 0.5));
}

async function forward(frame: unknown): Promise<void> {
  const { bridgeToken } = await chrome.storage.local.get("bridgeToken");
  if (typeof bridgeToken !== "string" || bridgeToken.length < 32) {
    await setState("error");
    return;
  }
  try {
    const response = await fetch(INGEST_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Token": bridgeToken,
      },
      body: JSON.stringify({
        connection_id: "browser-websocket-observer",
        session_id: "browser-session",
        frame,
      }),
    });
    if (!response.ok) throw new Error(`collector status ${response.status}`);
    attempt = 0;
    await setState("receiving");
  } catch {
    await setState("disconnected");
    await new Promise((resolve) => setTimeout(resolve, boundedBackoffMs()));
  }
}

async function forwardVisibleQuote(frame: Record<string, unknown>): Promise<void> {
  const { bridgeToken } = await chrome.storage.local.get("bridgeToken");
  if (typeof bridgeToken !== "string" || bridgeToken.length < 32) {
    await setState("error");
    return;
  }
  if (typeof frame.payload !== "string" || typeof frame.receivedAt !== "string") return;

  let quote: unknown;
  try {
    quote = JSON.parse(frame.payload);
  } catch {
    return;
  }
  if (typeof quote !== "object" || quote === null) return;
  const candidate = quote as Record<string, unknown>;
  if (
    candidate.instrument !== "EURUSD" ||
    typeof candidate.bid !== "string" ||
    typeof candidate.ask !== "string"
  ) {
    return;
  }

  try {
    const response = await fetch(PROVIDER_INGEST_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Token": bridgeToken,
      },
      body: JSON.stringify({
        connection_id: "browser-visible-dom",
        session_id: "browser-session",
        received_at: frame.receivedAt,
        semantics: "snapshot",
        payload: {
          instrument: "EURUSD",
          bid: candidate.bid,
          ask: candidate.ask,
          provider_event_time: null,
          observation_source: "visible_dom",
        },
        channel_metadata: {
          capture_method: "visible_dom",
          provider_transport: "wss_binary_arraybuffer",
          provider_timestamp_available: false,
        },
      }),
    });
    if (!response.ok) throw new Error(`collector status ${response.status}`);
    attempt = 0;
    await setState("receiving");
  } catch {
    await setState("disconnected");
    await new Promise((resolve) => setTimeout(resolve, boundedBackoffMs()));
  }
}

chrome.runtime.onMessage.addListener((message: unknown) => {
  if (typeof message !== "object" || message === null) return;
  const candidate = message as Record<string, unknown>;
  if (candidate.type === "GET_STATUS") return Promise.resolve({ state });
  if (candidate.type === "OBSERVER_READY") {
    if (state !== "receiving") void setState("waiting for EUR/USD");
    return;
  }
  if (candidate.type !== "CAPTURED_FRAME") return;
  // Preserve the last sanitized observation for local troubleshooting.
  void chrome.storage.local.set({ lastSanitizedDiscoveryFrame: candidate.frame });
  const frame = candidate.frame;
  if (
    typeof frame === "object" &&
    frame !== null &&
    (frame as Record<string, unknown>).frameType === "dom-visible-quote"
  ) {
    void forwardVisibleQuote(frame as Record<string, unknown>);
  } else {
    void forward(frame);
  }
});

chrome.runtime.onInstalled.addListener(() => {
  void setState("disconnected");
});
