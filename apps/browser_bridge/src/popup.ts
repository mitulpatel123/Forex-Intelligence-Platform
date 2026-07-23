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
  const rows = document.querySelector("#pairs");
  if (!rows) return;
  const byInstrument =
    typeof status.byInstrument === "object" && status.byInstrument !== null
      ? (status.byInstrument as Record<string, Record<string, unknown>>)
      : {};
  const pending =
    typeof status.pendingByInstrument === "object" &&
    status.pendingByInstrument !== null
      ? (status.pendingByInstrument as Record<string, unknown>)
      : {};
  const pairStatuses =
    typeof status.pairStatuses === "object" && status.pairStatuses !== null
      ? (status.pairStatuses as Record<string, { status?: unknown }>)
      : {};
  for (const instrument of SUPPORTED_INSTRUMENTS) {
    const stats = byInstrument[instrument] ?? {};
    const row = document.createElement("tr");
    const values: Array<string | number> = [
      instrument,
      String(pairStatuses[instrument]?.status ?? "MISSING"),
      Number(pending[instrument] ?? 0),
      Number(stats.retries ?? 0),
      Number(stats.dropped ?? 0),
      Number(stats.rejected ?? 0),
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.append(cell);
    }
    rows.append(row);
  }
});
import { SUPPORTED_INSTRUMENTS } from "./instruments.generated";
