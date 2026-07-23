import { CHANNEL, MAX_PAYLOAD_BYTES, isEurUsdCandidate, redactText } from "./schema";

const NativeWebSocket = window.WebSocket;

const ObserverWebSocket = new Proxy(NativeWebSocket, {
  construct(target, args, newTarget) {
    const socket = Reflect.construct(target, args, newTarget) as WebSocket;
    socket.addEventListener("message", (event: MessageEvent<unknown>) => {
      if (typeof event.data !== "string") return;
      if (!isEurUsdCandidate(event.data)) return;
      const sanitized = redactText(event.data);
      if (new TextEncoder().encode(sanitized).byteLength > MAX_PAYLOAD_BYTES) return;
      window.postMessage(
        {
          channel: CHANNEL,
          frameType: "websocket-text",
          receivedAt: new Date().toISOString(),
          payload: sanitized,
        },
        window.location.origin,
      );
    });
    return socket;
  },
});

window.WebSocket = ObserverWebSocket;

