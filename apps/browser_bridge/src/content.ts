import { CONFIG_CHANNEL, isCapturedFrame } from "./schema";

const documentSessionId = crypto.randomUUID();
let observerReady = false;

async function publishConfiguration(): Promise<void> {
  const { discoveryMode = false } = await chrome.storage.local.get("discoveryMode");
  window.postMessage(
    { channel: CONFIG_CHANNEL, discoveryMode: discoveryMode === true },
    window.location.origin,
  );
}

window.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.source !== window || !isCapturedFrame(event.data, event.origin)) return;
  if (event.data.frameType === "dom-visible-quote") observerReady = true;
  void chrome.runtime.sendMessage({
    type: "CAPTURED_FRAME",
    frame: event.data,
    documentSessionId,
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
