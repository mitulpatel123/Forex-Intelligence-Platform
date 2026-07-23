import {
  DISCOVERY_INGEST_URL,
  HEARTBEAT_URL,
  PROVIDER_INGEST_URL,
  browserIdentity,
  discoveryRequest,
  parseVisibleQuote,
  providerRequest,
} from "./bridge-protocol";
import { PersistentOutbox, type OutboxEvent } from "./outbox";
import { isCapturedFrame } from "./schema";
import {
  SUPPORTED_INSTRUMENTS,
  type SupportedInstrument,
} from "./instruments.generated";
import type { PairObserverState } from "./dom-observer";

type BridgeState = "disconnected" | "waiting for quotes" | "receiving" | "error";
type PairStatuses = Record<SupportedInstrument, PairObserverState>;

const RETRY_ALARM = "fip-bridge-outbox-retry";
const MAX_OUTBOX_SIZE = 1_000;
const FETCH_TIMEOUT_MS = 5_000;
let state: BridgeState = "disconnected";
let browserRunIdPromise: Promise<string> | null = null;
let latestPairStatuses = Object.fromEntries(
  SUPPORTED_INSTRUMENTS.map((instrument) => [
    instrument,
    { status: "MISSING", lastObservationAt: null },
  ]),
) as PairStatuses;

async function setState(next: BridgeState): Promise<void> {
  state = next;
  await chrome.storage.local.set({ bridgeState: next });
}

async function browserRunId(): Promise<string> {
  if (browserRunIdPromise) return browserRunIdPromise;
  browserRunIdPromise = (async () => {
    const stored = await chrome.storage.session.get("browserRunId");
    if (typeof stored.browserRunId === "string") return stored.browserRunId;
    const generated = crypto.randomUUID();
    await chrome.storage.session.set({ browserRunId: generated });
    return generated;
  })();
  return browserRunIdPromise;
}

async function identityFor(
  sender: chrome.runtime.MessageSender,
  documentSessionId: string,
) {
  return browserIdentity(
    await browserRunId(),
    sender.tab?.id ?? -1,
    sender.frameId ?? 0,
    documentSessionId,
  );
}

async function authenticatedFetch(
  url: string,
  body: Record<string, unknown>,
  timeoutMs = FETCH_TIMEOUT_MS,
): Promise<Response> {
  const { bridgeToken } = await chrome.storage.local.get("bridgeToken");
  if (typeof bridgeToken !== "string" || bridgeToken.length < 32) {
    await setState("error");
    throw new Error("missing bridge token");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Token": bridgeToken,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

const outbox = new PersistentOutbox({
  maxSize: MAX_OUTBOX_SIZE,
  storage: chrome.storage.local,
  deliver: async (event: OutboxEvent) => {
    const response = await authenticatedFetch(event.url, event.body);
    if (response.ok) return { acknowledged: true, retryable: false };
    const retryable =
      response.status === 401 ||
      response.status === 403 ||
      response.status === 408 ||
      response.status === 429 ||
      response.status >= 500;
    return { acknowledged: false, retryable };
  },
  schedule: async (when) => {
    await chrome.alarms.create(RETRY_ALARM, { when });
  },
  onDelivery: async (result) => {
    if (result === "acknowledged") await setState("receiving");
    else if (result === "retrying") await setState("disconnected");
    else await setState("error");
  },
});

function validDocumentSessionId(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9-]{36}$/i.test(value);
}

function senderOrigin(sender: chrome.runtime.MessageSender): string {
  if (typeof sender.origin === "string") return sender.origin;
  if (typeof sender.url !== "string") return "";
  try {
    return new URL(sender.url).origin;
  } catch {
    return "";
  }
}

async function sendHeartbeat(
  sender: chrome.runtime.MessageSender,
  documentSessionId: string,
  observerReady: boolean,
  pairStatuses: PairStatuses,
): Promise<void> {
  const identity = await identityFor(sender, documentSessionId);
  const snapshot = await outbox.snapshot();
  try {
    const response = await authenticatedFetch(
      HEARTBEAT_URL,
      {
        connection_id: identity.connectionId,
        session_id: identity.sessionId,
        observer_ready: observerReady,
        bridge_state: state,
        outbox_pending: snapshot.pending,
        outbox_produced: snapshot.stats.produced,
        outbox_acknowledged: snapshot.stats.acknowledged,
        outbox_retries: snapshot.stats.retries,
        outbox_dropped: snapshot.stats.dropped,
        outbox_rejected: snapshot.stats.rejected,
        pairs: Object.fromEntries(
          SUPPORTED_INSTRUMENTS.map((instrument) => [
            instrument,
            {
              target_status: pairStatuses[instrument].status,
              last_observation_time: pairStatuses[instrument].lastObservationAt,
              outbox_pending: snapshot.pendingByInstrument[instrument],
              outbox_produced: snapshot.stats.byInstrument[instrument].produced,
              outbox_acknowledged:
                snapshot.stats.byInstrument[instrument].acknowledged,
              outbox_retries: snapshot.stats.byInstrument[instrument].retries,
              outbox_dropped: snapshot.stats.byInstrument[instrument].dropped,
              outbox_rejected: snapshot.stats.byInstrument[instrument].rejected,
            },
          ]),
        ),
      },
      3_000,
    );
    if (!response.ok) throw new Error(`heartbeat status ${response.status}`);
  } catch {
    await setState("disconnected");
  }
}

async function queueCapturedFrame(
  candidate: Record<string, unknown>,
  sender: chrome.runtime.MessageSender,
): Promise<Record<string, unknown>> {
  if (
    !validDocumentSessionId(candidate.documentSessionId) ||
    !isCapturedFrame(candidate.frame, senderOrigin(sender))
  ) {
    return { accepted: false, reason: "invalid frame" };
  }
  const frame = candidate.frame;
  const identity = await identityFor(sender, candidate.documentSessionId);
  const eventId = crypto.randomUUID();
  const quote = parseVisibleQuote(frame);
  let event: OutboxEvent;
  if (quote) {
    event = {
      eventId,
      kind: "visible_quote",
      instrument: quote.instrument,
      url: PROVIDER_INGEST_URL,
      body: providerRequest(eventId, identity, frame, quote),
      attempts: 0,
      nextAttemptAt: Date.now(),
    };
  } else {
    const { discoveryMode = false } = await chrome.storage.local.get("discoveryMode");
    if (discoveryMode !== true) {
      return { accepted: false, reason: "discovery mode disabled" };
    }
    event = {
      eventId,
      kind: "discovery",
      instrument: null,
      url: DISCOVERY_INGEST_URL,
      body: discoveryRequest(eventId, identity, frame),
      attempts: 0,
      nextAttemptAt: Date.now(),
    };
  }
  const queued = await outbox.enqueue(event);
  if (queued) await outbox.drain();
  return { accepted: queued, eventId, queued };
}

async function handleMessage(
  message: unknown,
  sender: chrome.runtime.MessageSender,
): Promise<Record<string, unknown>> {
  if (typeof message !== "object" || message === null) return { accepted: false };
  const candidate = message as Record<string, unknown>;
  if (candidate.type === "GET_STATUS") {
    const snapshot = await outbox.snapshot();
    const { discoveryMode = false } = await chrome.storage.local.get("discoveryMode");
    return {
      state,
      discoveryMode,
      ...snapshot.stats,
      pending: snapshot.pending,
      pendingByInstrument: snapshot.pendingByInstrument,
      byInstrument: snapshot.stats.byInstrument,
      pairStatuses: latestPairStatuses,
    };
  }
  if (
    (candidate.type === "OBSERVER_READY" ||
      candidate.type === "BRIDGE_HEARTBEAT" ||
      candidate.type === "OBSERVER_STOPPED") &&
    validDocumentSessionId(candidate.documentSessionId)
  ) {
    const observerReady =
      candidate.type === "BRIDGE_HEARTBEAT" && candidate.observerReady === true;
    if (candidate.type === "OBSERVER_READY") await setState("waiting for quotes");
    if (candidate.type === "OBSERVER_STOPPED") await setState("disconnected");
    const incoming =
      typeof candidate.pairStatuses === "object" && candidate.pairStatuses !== null
        ? (candidate.pairStatuses as Record<string, PairObserverState>)
        : {};
    const pairStatuses = Object.fromEntries(
      SUPPORTED_INSTRUMENTS.map((instrument) => {
        const pair = incoming[instrument];
        return [
          instrument,
          pair &&
          ["FOUND", "READY", "MISSING", "AMBIGUOUS", "STALE"].includes(pair.status)
            ? pair
            : { status: "MISSING", lastObservationAt: null },
        ];
      }),
    ) as PairStatuses;
    latestPairStatuses = pairStatuses;
    await sendHeartbeat(sender, candidate.documentSessionId, observerReady, pairStatuses);
    return { accepted: true };
  }
  if (candidate.type === "CAPTURED_FRAME") return queueCapturedFrame(candidate, sender);
  return { accepted: false };
}

chrome.runtime.onMessage.addListener((message, sender) => handleMessage(message, sender));

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === RETRY_ALARM) void outbox.drain();
});

chrome.runtime.onStartup.addListener(() => {
  void outbox.drain();
});

chrome.runtime.onInstalled.addListener(() => {
  void chrome.storage.local.set({ bridgeState: "disconnected", discoveryMode: false });
  void chrome.storage.local.remove("lastSanitizedDiscoveryFrame");
  void outbox.drain();
});
