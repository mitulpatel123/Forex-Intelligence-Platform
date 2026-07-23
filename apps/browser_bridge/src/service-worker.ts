type BridgeState = "connected" | "disconnected" | "waiting for EUR/USD" | "receiving" | "error";

const INGEST_URL = "http://127.0.0.1:8001/ingest/discovery";
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

chrome.runtime.onMessage.addListener((message: unknown) => {
  if (typeof message !== "object" || message === null) return;
  const candidate = message as Record<string, unknown>;
  if (candidate.type === "GET_STATUS") return Promise.resolve({ state });
  if (candidate.type !== "CAPTURED_FRAME") return;
  // Frames are captured for discovery. They are not normalized until a confirmed
  // provider schema mapping is added; this prevents an invented live adapter.
  void chrome.storage.local.set({ lastSanitizedDiscoveryFrame: candidate.frame });
  void forward(candidate.frame);
});

chrome.runtime.onInstalled.addListener(() => {
  void setState("disconnected");
});

