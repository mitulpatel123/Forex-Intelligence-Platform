import {
  CONFIG_CHANNEL,
  isCapturedFrame,
  isPairStatusFrame,
  type PairStatusFrame,
} from "./schema";
import { SUPPORTED_INSTRUMENTS } from "./instruments.generated";

const documentSessionId = crypto.randomUUID();
const observationSequences = new Map<string, number>();
let observerReady = false;
let pairStatuses: PairStatusFrame["pairs"] = Object.fromEntries(
  SUPPORTED_INSTRUMENTS.map((instrument) => [
    instrument,
    { status: "MISSING", lastObservationAt: null },
  ]),
) as PairStatusFrame["pairs"];

async function publishConfiguration(): Promise<void> {
  const { discoveryMode = false } = await chrome.storage.local.get("discoveryMode");
  window.postMessage(
    { channel: CONFIG_CHANNEL, discoveryMode: discoveryMode === true },
    window.location.origin,
  );
}

window.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.source !== window) return;
  if (isPairStatusFrame(event.data, event.origin)) {
    pairStatuses = structuredClone(event.data.pairs);
    observerReady = SUPPORTED_INSTRUMENTS.some((instrument) =>
      ["FOUND", "READY", "STALE"].includes(pairStatuses[instrument].status),
    );
    return;
  }
  if (!isCapturedFrame(event.data, event.origin)) return;
  if (event.data.frameType === "dom-visible-quote") observerReady = true;
  let observationSequence: number | null = null;
  if (event.data.frameType === "dom-visible-quote") {
    try {
      const parsed = JSON.parse(event.data.payload) as { instrument?: unknown };
      if (
        typeof parsed.instrument === "string" &&
        SUPPORTED_INSTRUMENTS.includes(
          parsed.instrument as (typeof SUPPORTED_INSTRUMENTS)[number],
        )
      ) {
        observationSequence = (observationSequences.get(parsed.instrument) ?? 0) + 1;
        observationSequences.set(parsed.instrument, observationSequence);
      }
    } catch {
      observationSequence = null;
    }
  }
  void chrome.runtime.sendMessage({
    type: "CAPTURED_FRAME",
    frame: event.data,
    documentSessionId,
    observationSequence,
  });
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === "local" && "discoveryMode" in changes) void publishConfiguration();
});

void publishConfiguration();
void chrome.runtime.sendMessage({ type: "OBSERVER_READY", documentSessionId });

const heartbeatTimer = window.setInterval(() => {
  void chrome.runtime.sendMessage({
    type: "BRIDGE_HEARTBEAT",
    documentSessionId,
    observerReady,
    pairStatuses,
  });
}, 2_000);

window.addEventListener(
  "pagehide",
  () => {
    window.clearInterval(heartbeatTimer);
    void chrome.runtime.sendMessage({ type: "OBSERVER_STOPPED", documentSessionId });
  },
  { once: true },
);
