import { TargetedQuoteObserver } from "./dom-observer";
import {
  CHANNEL,
  CONFIG_CHANNEL,
  MAX_PAYLOAD_BYTES,
  isEurUsdCandidate,
  redactText,
} from "./schema";

const NativeWebSocket = window.WebSocket;
let discoveryMode = false;

window.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.source !== window || event.origin !== window.location.origin) return;
  if (typeof event.data !== "object" || event.data === null) return;
  const config = event.data as Record<string, unknown>;
  if (config.channel === CONFIG_CHANNEL && typeof config.discoveryMode === "boolean") {
    discoveryMode = config.discoveryMode;
  }
});

async function inspectDiscoveryFrame(data: unknown): Promise<void> {
  if (!discoveryMode) return;
  let payload: string;
  let frameType: "websocket-text" | "websocket-binary-utf8";

  if (typeof data === "string") {
    payload = data;
    frameType = "websocket-text";
  } else if (data instanceof ArrayBuffer) {
    if (data.byteLength > MAX_PAYLOAD_BYTES) return;
    payload = new TextDecoder().decode(new Uint8Array(data));
    frameType = "websocket-binary-utf8";
  } else if (ArrayBuffer.isView(data)) {
    if (data.byteLength > MAX_PAYLOAD_BYTES) return;
    payload = new TextDecoder().decode(
      new Uint8Array(data.buffer, data.byteOffset, data.byteLength),
    );
    frameType = "websocket-binary-utf8";
  } else if (data instanceof Blob) {
    if (data.size > MAX_PAYLOAD_BYTES) return;
    payload = await data.text();
    frameType = "websocket-binary-utf8";
  } else {
    return;
  }

  if (!isEurUsdCandidate(payload)) return;
  const sanitized = redactText(payload);
  if (new TextEncoder().encode(sanitized).byteLength > MAX_PAYLOAD_BYTES) return;
  window.postMessage(
    {
      channel: CHANNEL,
      frameType,
      receivedAt: new Date().toISOString(),
      payload: sanitized,
    },
    window.location.origin,
  );
}

const ObserverWebSocket = new Proxy(NativeWebSocket, {
  construct(target, args, newTarget) {
    const socket = Reflect.construct(target, args, newTarget) as WebSocket;
    socket.addEventListener("message", (event: MessageEvent<unknown>) => {
      void inspectDiscoveryFrame(event.data);
    });
    return socket;
  },
});

window.WebSocket = ObserverWebSocket;

const quoteObserver = new TargetedQuoteObserver((quote) => {
  window.postMessage(
    {
      channel: CHANNEL,
      frameType: "dom-visible-quote",
      receivedAt: new Date().toISOString(),
      payload: JSON.stringify({ instrument: "EURUSD", ...quote }),
    },
    window.location.origin,
  );
});

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", () => quoteObserver.start(), { once: true });
} else {
  quoteObserver.start();
}
