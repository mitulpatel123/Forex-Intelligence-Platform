import { CHANNEL, MAX_PAYLOAD_BYTES, isEurUsdCandidate, redactText } from "./schema";

const NativeWebSocket = window.WebSocket;
let lastVisibleQuote = "";

async function inspectFrame(data: unknown): Promise<void> {
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
      void inspectFrame(event.data);
    });
    return socket;
  },
});

window.WebSocket = ObserverWebSocket;

function visibleLeafText(root: Element): string[] {
  return Array.from(root.querySelectorAll("*"))
    .filter((element) => element.children.length === 0)
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    })
    .map((element) => element.textContent?.trim() ?? "")
    .filter(Boolean);
}

function findVisibleEurUsdQuote(): { bid: string; ask: string } | null {
  const symbolLeaves = Array.from(document.querySelectorAll("body *")).filter(
    (element) => element.children.length === 0 && element.textContent?.trim() === "EURUSD",
  );
  for (const symbol of symbolLeaves) {
    let candidate: Element | null = symbol.parentElement;
    for (let depth = 0; candidate && depth < 6; depth += 1) {
      const texts = visibleLeafText(candidate);
      const prices = texts.filter((text) => /^\d+\.\d{4,6}$/.test(text));
      if (texts.includes("EURUSD") && prices.length >= 2) {
        const bidText = prices[0];
        const askText = prices[1];
        if (!bidText || !askText) {
          candidate = candidate.parentElement;
          continue;
        }
        const bid = Number(bidText);
        const ask = Number(askText);
        if (
          Number.isFinite(bid) &&
          Number.isFinite(ask) &&
          bid > 0.5 &&
          bid < 2 &&
          ask >= bid &&
          ask - bid <= 0.01
        ) {
          return { bid: bidText, ask: askText };
        }
      }
      candidate = candidate.parentElement;
    }
  }
  return null;
}

function inspectVisibleQuote(): void {
  const quote = findVisibleEurUsdQuote();
  if (!quote) return;
  const quoteKey = `${quote.bid}:${quote.ask}`;
  if (quoteKey === lastVisibleQuote) return;
  lastVisibleQuote = quoteKey;
  window.postMessage(
    {
      channel: CHANNEL,
      frameType: "dom-visible-quote",
      receivedAt: new Date().toISOString(),
      payload: JSON.stringify({
        instrument: "EURUSD",
        bid: quote.bid,
        ask: quote.ask,
      }),
    },
    window.location.origin,
  );
}

let inspectionQueued = false;
const quoteObserver = new MutationObserver(() => {
  if (inspectionQueued) return;
  inspectionQueued = true;
  requestAnimationFrame(() => {
    inspectionQueued = false;
    inspectVisibleQuote();
  });
});

quoteObserver.observe(document, { childList: true, characterData: true, subtree: true });
window.addEventListener("DOMContentLoaded", inspectVisibleQuote, { once: true });
