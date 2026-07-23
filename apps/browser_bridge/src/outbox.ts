export type OutboxKind = "visible_quote" | "discovery";

export type OutboxEvent = {
  eventId: string;
  kind: OutboxKind;
  url: string;
  body: Record<string, unknown>;
  attempts: number;
  nextAttemptAt: number;
};

export type OutboxStats = {
  produced: number;
  acknowledged: number;
  retries: number;
  dropped: number;
  rejected: number;
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
  onDelivery?: (result: "acknowledged" | "retrying" | "dropped") => Promise<void>;
};

const OUTBOX_KEY = "bridgeOutbox";
const STATS_KEY = "bridgeStats";

export const EMPTY_STATS: OutboxStats = {
  produced: 0,
  acknowledged: 0,
  retries: 0,
  dropped: 0,
  rejected: 0,
};

function isOutboxEvent(value: unknown): value is OutboxEvent {
  if (typeof value !== "object" || value === null) return false;
  const event = value as Record<string, unknown>;
  return (
    typeof event.eventId === "string" &&
    (event.kind === "visible_quote" || event.kind === "discovery") &&
    typeof event.url === "string" &&
    typeof event.body === "object" &&
    event.body !== null &&
    typeof event.attempts === "number" &&
    typeof event.nextAttemptAt === "number"
  );
}

function parseStats(value: unknown): OutboxStats {
  if (typeof value !== "object" || value === null) return { ...EMPTY_STATS };
  const stats = value as Record<string, unknown>;
  return {
    produced: typeof stats.produced === "number" ? stats.produced : 0,
    acknowledged: typeof stats.acknowledged === "number" ? stats.acknowledged : 0,
    retries: typeof stats.retries === "number" ? stats.retries : 0,
    dropped: typeof stats.dropped === "number" ? stats.dropped : 0,
    rejected: typeof stats.rejected === "number" ? stats.rejected : 0,
  };
}

export class PersistentOutbox {
  private serial: Promise<unknown> = Promise.resolve();
  private draining: Promise<void> | null = null;
  private readonly now: () => number;

  constructor(private readonly options: OutboxOptions) {
    this.now = options.now ?? Date.now;
  }

  private async load(): Promise<{ events: OutboxEvent[]; stats: OutboxStats }> {
    const stored = await this.options.storage.get([OUTBOX_KEY, STATS_KEY]);
    return {
      events: Array.isArray(stored[OUTBOX_KEY])
        ? stored[OUTBOX_KEY].filter(isOutboxEvent)
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
      stats.produced += 1;
      if (events.length >= this.options.maxSize) {
        stats.dropped += 1;
        await this.save(events, stats);
        await this.options.onDelivery?.("dropped");
        return false;
      }
      events.push(event);
      await this.save(events, stats);
      return true;
    });
  }

  async snapshot(): Promise<{ pending: number; stats: OutboxStats }> {
    const { events, stats } = await this.runSerial(() => this.load());
    return { pending: events.length, stats };
  }

  async drain(): Promise<void> {
    if (this.draining) return this.draining;
    this.draining = this.drainLoop().finally(() => {
      this.draining = null;
    });
    return this.draining;
  }

  private async drainLoop(): Promise<void> {
    while (true) {
      const current = await this.runSerial(() => this.load());
      const event = current.events[0];
      if (!event) return;
      if (event.nextAttemptAt > this.now()) {
        await this.options.schedule(event.nextAttemptAt);
        return;
      }

      let result: DeliveryResult;
      try {
        result = await this.options.deliver(event);
      } catch {
        result = { acknowledged: false, retryable: true };
      }

      if (result.acknowledged) {
        await this.runSerial(async () => {
          const { events, stats } = await this.load();
          const remaining = events.filter((candidate) => candidate.eventId !== event.eventId);
          stats.acknowledged += 1;
          await this.save(remaining, stats);
        });
        await this.options.onDelivery?.("acknowledged");
        continue;
      }

      if (!result.retryable) {
        await this.runSerial(async () => {
          const { events, stats } = await this.load();
          const remaining = events.filter((candidate) => candidate.eventId !== event.eventId);
          stats.dropped += 1;
          stats.rejected += 1;
          await this.save(remaining, stats);
        });
        await this.options.onDelivery?.("dropped");
        continue;
      }

      const retryAt = this.now() + Math.min(30_000, 500 * 2 ** Math.min(event.attempts, 6));
      await this.runSerial(async () => {
        const { events, stats } = await this.load();
        const candidate = events.find((item) => item.eventId === event.eventId);
        if (candidate) {
          candidate.attempts += 1;
          candidate.nextAttemptAt = retryAt;
        }
        stats.retries += 1;
        await this.save(events, stats);
      });
      await this.options.onDelivery?.("retrying");
      await this.options.schedule(retryAt);
      return;
    }
  }
}
