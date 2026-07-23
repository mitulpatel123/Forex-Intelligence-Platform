import { isCapturedFrame } from "./schema";

window.addEventListener("message", (event: MessageEvent<unknown>) => {
  if (event.source !== window || !isCapturedFrame(event.data, event.origin)) return;
  void chrome.runtime.sendMessage({ type: "CAPTURED_FRAME", frame: event.data });
});

void chrome.runtime.sendMessage({ type: "OBSERVER_READY" });
