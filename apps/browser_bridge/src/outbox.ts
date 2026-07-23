import {
  SUPPORTED_INSTRUMENTS,
  type SupportedInstrument,
  isSupportedInstrument,
} from "./instruments.generated";

export type OutboxKind = "visible_quote" | "discovery";

export type OutboxEvent = {
  eventId: string;
  kind: OutboxKind;
  instrument: SupportedInstrument | null;
  url: string;
  body: Record<string, unknown>;
  attempts: number;
  nextAttemptAt: number;
};

export type PairOutboxStats = {
  produced: number;
  acknowledged: number;
  retries: number;
  dropped: number;
  rejected: number;
};

export type OutboxStats = PairOutboxStats & {
  byInstrument: Record<SupportedInstrument, PairOutboxStats>;
};

export type OutboxSnapshot = {
  pending: number;
  pendingByInstrument: Record<SupportedInstrument, number>;
  stats: OutboxStats;
};

export type DeliveryResult = {
  acknowledged: boolean;
  retryable: boolean;
};

export interface StorageLike {
  get(keys: string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}

export type OutboxOptions = {
  maxSize: number;
  storage: StorageLike;
  deliver: (event: OutboxEvent) => Promise<DeliveryResult>;
  schedule: (when: number) => Promise<void>;
  now?: () => number;
  onDelivery?: (
    result: "acknowledged" | "retrying" | "dropped",
    event: OutboxEvent,
  ) => Promise<void>;
};

const OUTBOX_KEY = "bridgeOutbox";
const STATS_KEY = "bridgeStats";
const GROUPS = [...SUPPORTED_INSTRUMENTS, "DISCOVERY"] as const;

function emptyPairStats(): PairOutboxStats {
  return { produced: 0, acknowledged: 0, retries: 0, dropped: 0, rejected: 0 };
}

export function emptyStats(): OutboxStats {
  return {
    ...emptyPairStats(),
    byInstrument: Object.fromEntries(
      SUPPORTED_INSTRUMENTS.map((instrument) => [instrument, emptyPairStats()]),
    ) as Record<SupportedInstrument, PairOutboxStats>,
  };
}

export const EMPTY_STATS = emptyStats();

function parseEvent(value: unknown): OutboxEvent | null {
  if (typeof value !== "object" || value === null) return null;
  const event = value as Record<string, unknown>;
  if (
    typeof event.eventId !== "string" ||
    (event.kind !== "visible_quote" && event.kind !== "discovery") ||
    typeof event.url !== "string" ||
    typeof event.body !== "object" ||
    event.body === null ||
    typeof event.attempts !== "number" ||
    typeof event.nextAttemptAt !== "number"
  ) {
    return null;
  }
  const body = event.body as Record<string, unknown>;
  const payload =
    typeof body.payload === "object" && body.payload !== null
      ? (body.payload as Record<string, unknown>)
      : {};
  const candidate = event.instrument ?? body.instrument ?? payload.instrument;
  const instrument = isSupportedInstrument(candidate) ? candidate : null;
  return {
    eventId: event.eventId,
    kind: event.kind,
    instrument,
    url: event.url,
    body,
    attempts: event.attempts,
    nextAttemptAt: event.nextAttemptAt,
  };
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;
}

function parsePairStats(value: unknown): PairOutboxStats {
  const stats = typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  return {
    produced: number(stats.produced),
    acknowledged: number(stats.acknowledged),
    retries: number(stats.retries),
    dropped: number(stats.dropped),
    rejected: number(stats.rejected),
  };
}

function parseStats(value: unknown): OutboxStats {
  const aggregate = parsePairStats(value);
  const stored = typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  const byInstrument =
    typeof stored.byInstrument === "object" && stored.byInstrument !== null
      ? (stored.byInstrument as Record<string, unknown>)
      : {};
  return {
    ...aggregate,
    byInstrument: Object.fromEntries(
      SUPPORTED_INSTRUMENTS.map((instrument) => [
        instrument,
        parsePairStats(byInstrument[instrument]),
      ]),
    ) as Record<SupportedInstrument, PairOutboxStats>,
  };
}

function increment(
  stats: OutboxStats,
  event: OutboxEvent,
  field: keyof PairOutboxStats,
): void {
  stats[field] += 1;
  if (event.instrument) stats.byInstrument[event.instrument][field] += 1;
}

function eventGroup(event: OutboxEvent): (typeof GROUPS)[number] {
  return event.instrument ?? "DISCOVERY";
}

export class PersistentOutbox {
  private serial: Promise<unknown> = Promise.resolve();
  private draining: Promise<void> | null = null;
  private readonly now: () => number;
  private cursor = 0;

  constructor(private readonly options: OutboxOptions) {
    this.now = options.now ?? Date.now;
  }

  private async load(): Promise<{ events: OutboxEvent[]; stats: OutboxStats }> {
    const stored = await this.options.storage.get([OUTBOX_KEY, STATS_KEY]);
    return {
      events: Array.isArray(stored[OUTBOX_KEY])
        ? stored[OUTBOX_KEY]
            .map(parseEvent)
            .filter((event): event is OutboxEvent => event !== null)
        : [],
      stats: parseStats(stored[STATS_KEY]),
    };
  }

  private async save(events: OutboxEvent[], stats: OutboxStats): Promise<void> {
    await this.options.storage.set({ [OUTBOX_KEY]: events, [STATS_KEY]: stats });
  }

  private runSerial<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.serial.then(operation, operation);
    this.serial = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  }

  async enqueue(event: OutboxEvent): Promise<boolean> {
    return this.runSerial(async () => {
      const { events, stats } = await this.load();
      increment(stats, event, "produced");
      const groupCapacity = Math.max(
        1,
        Math.floor(this.options.maxSize / GROUPS.length),
      );
      const groupDepth = events.filter(
        (candidate) => eventGroup(candidate) === eventGroup(event),
      ).length;
      if (
        events.length >= this.options.maxSize ||
        groupDepth >= groupCapacity
      ) {
        increment(stats, event, "dropped");
        await this.save(events, stats);
        await this.options.onDelivery?.("dropped", event);
        return false;
      }
      events.push(event);
      await this.save(events, stats);
      return true;
    });
  }

  async snapshot(): Promise<OutboxSnapshot> {
    const { events, stats } = await this.runSerial(() => this.load());
    const pendingByInstrument = Object.fromEntries(
      SUPPORTED_INSTRUMENTS.map((instrument) => [
        instrument,
        events.filter((event) => event.instrument === instrument).length,
      ]),
    ) as Record<SupportedInstrument, number>;
    return { pending: events.length, pendingByInstrument, stats };
  }

  async drain(): Promise<void> {
    if (this.draining) return this.draining;
    this.draining = this.drainLoop().finally(() => {
      this.draining = null;
    });
    return this.draining;
  }

  private selectNext(events: OutboxEvent[], attempted: Set<string>): OutboxEvent | null {
    for (let offset = 0; offset < GROUPS.length; offset += 1) {
      const index = (this.cursor + offset) % GROUPS.length;
      const group = GROUPS[index];
      const head = events.find((candidate) => eventGroup(candidate) === group);
      if (
        head &&
        head.nextAttemptAt <= this.now() &&
        !attempted.has(head.eventId)
      ) {
        this.cursor = (index + 1) % GROUPS.length;
        return head;
      }
    }
    return null;
  }

  private groupHeads(events: OutboxEvent[]): OutboxEvent[] {
    return GROUPS.flatMap((group) => {
      const head = events.find((candidate) => eventGroup(candidate) === group);
      return head ? [head] : [];
    });
  }

  private async drainLoop(): Promise<void> {
    const attempted = new Set<string>();
    while (true) {
      const current = await this.runSerial(() => this.load());
      if (current.events.length === 0) return;
      const event = this.selectNext(current.events, attempted);
      if (!event) {
        const nextAttempt = Math.min(
          ...this.groupHeads(current.events).map((candidate) => candidate.nextAttemptAt),
        );
        await this.options.schedule(Math.max(this.now(), nextAttempt));
        return;
      }
      attempted.add(event.eventId);

      let result: DeliveryResult;
      try {
        result = await this.options.deliver(event);
      } catch {
        result = { acknowledged: false, retryable: true };
      }

      if (result.acknowledged) {
        await this.runSerial(async () => {
          const { events, stats } = await this.load();
          const candidate = events.find((item) => item.eventId === event.eventId);
          if (!candidate) return;
          increment(stats, candidate, "acknowledged");
          await this.save(
            events.filter((item) => item.eventId !== event.eventId),
            stats,
          );
        });
        await this.options.onDelivery?.("acknowledged", event);
        continue;
      }

      if (!result.retryable) {
        await this.runSerial(async () => {
          const { events, stats } = await this.load();
          const candidate = events.find((item) => item.eventId === event.eventId);
          if (!candidate) return;
          increment(stats, candidate, "dropped");
          increment(stats, candidate, "rejected");
          await this.save(
            events.filter((item) => item.eventId !== event.eventId),
            stats,
          );
        });
        await this.options.onDelivery?.("dropped", event);
        continue;
      }

      const retryAt = this.now() + Math.min(30_000, 500 * 2 ** Math.min(event.attempts, 6));
      await this.runSerial(async () => {
        const { events, stats } = await this.load();
        const candidate = events.find((item) => item.eventId === event.eventId);
        if (candidate) {
          candidate.attempts += 1;
          candidate.nextAttemptAt = retryAt;
          increment(stats, candidate, "retries");
        }
        await this.save(events, stats);
      });
      await this.options.onDelivery?.("retrying", event);
    }
  }
}
