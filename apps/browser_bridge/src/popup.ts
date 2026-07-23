const fields = [
  "status",
  "pending",
  "produced",
  "acknowledged",
  "retries",
  "dropped",
  "rejected",
  "discoveryMode",
] as const;

void chrome.runtime.sendMessage({ type: "GET_STATUS" }).then((response: unknown) => {
  if (typeof response !== "object" || response === null) return;
  const status = response as Record<string, unknown>;
  for (const field of fields) {
    const element = document.querySelector(`#${field}`);
    const key = field === "status" ? "state" : field;
    if (!element) continue;
    if (field === "discoveryMode") {
      element.textContent = status[key] === true ? "ON" : "OFF";
    } else {
      element.textContent = String(status[key] ?? "0");
    }
  }
});
