import { describe, expect, it, vi } from "vitest";
import {
  PersistentOutbox,
  type OutboxEvent,
  type StorageLike,
} from "../src/outbox";
import type { SupportedInstrument } from "../src/instruments.generated";

class MemoryStorage implements StorageLike {
  values: Record<string, unknown> = {};

  async get(keys: string[]): Promise<Record<string, unknown>> {
    return Object.fromEntries(keys.map((key) => [key, this.values[key]]));
  }

  async set(items: Record<string, unknown>): Promise<void> {
    Object.assign(this.values, structuredClone(items));
  }
}

function event(
  id: string,
  instrument: SupportedInstrument = "EURUSD",
  now = 1_000,
): OutboxEvent {
  return {
    eventId: id,
    kind: "visible_quote",
    instrument,
    url: "http://127.0.0.1:8001/ingest/provider",
    body: { event_id: id, instrument },
    attempts: 0,
    nextAttemptAt: now,
  };
}

function outbox(
  storage: MemoryStorage,
  deliver: (candidate: OutboxEvent) => Promise<{
    acknowledged: boolean;
    retryable: boolean;
  }>,
  options: { maxSize?: number; now?: () => number } = {},
): PersistentOutbox {
  return new PersistentOutbox({
    maxSize: options.maxSize ?? 100,
    storage,
    deliver,
    schedule: vi.fn(async () => undefined),
    now: options.now ?? (() => 1_000),
  });
}

describe("persistent fair browser outbox", () => {
  it("exposes aggregate and per-pair enqueue counts", async () => {
    const queue = outbox(new MemoryStorage(), vi.fn());
    await queue.enqueue(event("eur", "EURUSD"));
    await queue.enqueue(event("jpy", "USDJPY"));
    const snapshot = await queue.snapshot();
    expect(snapshot.pending).toBe(2);
    expect(snapshot.pendingByInstrument).toEqual({
      EURUSD: 1,
      GBPUSD: 0,
      USDJPY: 1,
      AUDUSD: 0,
    });
    expect(snapshot.stats.produced).toBe(2);
    expect(snapshot.stats.byInstrument.EURUSD.produced).toBe(1);
    expect(snapshot.stats.byInstrument.USDJPY.produced).toBe(1);
  });

  it("drains round-robin while preserving FIFO within each pair", async () => {
    const storage = new MemoryStorage();
    const delivered: string[] = [];
    const queue = outbox(storage, async (candidate) => {
      delivered.push(candidate.eventId);
      return { acknowledged: true, retryable: false };
    });
    await queue.enqueue(event("eur-1"));
    await queue.enqueue(event("eur-2"));
    await queue.enqueue(event("eur-3"));
    await queue.enqueue(event("gbp-1", "GBPUSD"));
    await queue.enqueue(event("jpy-1", "USDJPY"));
    await queue.enqueue(event("aud-1", "AUDUSD"));
    await queue.drain();
    expect(delivered).toEqual(["eur-1", "gbp-1", "jpy-1", "aud-1", "eur-2", "eur-3"]);
  });

  it("persists an outage and retries the same stable event after restart", async () => {
    const storage = new MemoryStorage();
    let now = 1_000;
    const delivered: string[] = [];
    const deliver = vi
      .fn()
      .mockImplementationOnce(async (candidate: OutboxEvent) => {
        delivered.push(candidate.eventId);
        throw new Error("temporary failure");
      })
      .mockImplementationOnce(async (candidate: OutboxEvent) => {
        delivered.push(candidate.eventId);
        return { acknowledged: true, retryable: false };
      });
    const first = outbox(storage, deliver, { now: () => now });
    await first.enqueue(event("event-1"));
    await first.drain();
    let snapshot = await first.snapshot();
    expect(snapshot.pending).toBe(1);
    expect(snapshot.stats.retries).toBe(1);
    expect(snapshot.stats.byInstrument.EURUSD.retries).toBe(1);

    now = 1_500;
    const restored = outbox(storage, deliver, { now: () => now });
    await restored.drain();
    snapshot = await restored.snapshot();
    expect(delivered).toEqual(["event-1", "event-1"]);
    expect(snapshot.pending).toBe(0);
    expect(snapshot.stats.acknowledged).toBe(1);
  });

  it("does not let one failing pair starve other pairs", async () => {
    const storage = new MemoryStorage();
    const delivered: string[] = [];
    const queue = outbox(storage, async (candidate) => {
      delivered.push(candidate.eventId);
      return candidate.instrument === "EURUSD"
        ? { acknowledged: false, retryable: true }
        : { acknowledged: true, retryable: false };
    });
    await queue.enqueue(event("eur-fail"));
    await queue.enqueue(event("gbp-ok", "GBPUSD"));
    await queue.enqueue(event("jpy-ok", "USDJPY"));
    await queue.enqueue(event("aud-ok", "AUDUSD"));
    await queue.drain();
    expect(delivered).toEqual(["eur-fail", "gbp-ok", "jpy-ok", "aud-ok"]);
    const snapshot = await queue.snapshot();
    expect(snapshot.pendingByInstrument.EURUSD).toBe(1);
    expect(snapshot.pending).toBe(1);
  });

  it("keeps later same-pair events behind a retrying head", async () => {
    const storage = new MemoryStorage();
    let now = 1_000;
    const delivered: string[] = [];
    let eurHeadAttempts = 0;
    const queue = outbox(
      storage,
      async (candidate) => {
        delivered.push(candidate.eventId);
        if (candidate.eventId === "eur-1" && eurHeadAttempts++ === 0) {
          return { acknowledged: false, retryable: true };
        }
        return { acknowledged: true, retryable: false };
      },
      { now: () => now },
    );
    await queue.enqueue(event("eur-1"));
    await queue.enqueue(event("eur-2"));
    await queue.enqueue(event("gbp-1", "GBPUSD"));

    await queue.drain();
    expect(delivered).toEqual(["eur-1", "gbp-1"]);
    expect((await queue.snapshot()).pendingByInstrument.EURUSD).toBe(2);

    now = 1_500;
    await queue.drain();
    expect(delivered).toEqual(["eur-1", "gbp-1", "eur-1", "eur-2"]);
    expect((await queue.snapshot()).pending).toBe(0);
  });

  it("bounds capacity and attributes the drop to its pair", async () => {
    const queue = outbox(new MemoryStorage(), vi.fn(), { maxSize: 1 });
    expect(await queue.enqueue(event("event-1"))).toBe(true);
    expect(await queue.enqueue(event("event-2", "AUDUSD"))).toBe(false);
    const snapshot = await queue.snapshot();
    expect(snapshot.pending).toBe(1);
    expect(snapshot.stats.dropped).toBe(1);
    expect(snapshot.stats.byInstrument.AUDUSD.dropped).toBe(1);
  });

  it("reserves capacity so one heavy pair cannot consume every slot", async () => {
    const queue = outbox(new MemoryStorage(), vi.fn(), { maxSize: 5 });
    expect(await queue.enqueue(event("eur-1"))).toBe(true);
    expect(await queue.enqueue(event("eur-2"))).toBe(false);
    expect(await queue.enqueue(event("aud-1", "AUDUSD"))).toBe(true);
    const snapshot = await queue.snapshot();
    expect(snapshot.pendingByInstrument).toMatchObject({ EURUSD: 1, AUDUSD: 1 });
  });

  it("removes and counts permanent backend rejections", async () => {
    const queue = outbox(new MemoryStorage(), async () => ({
      acknowledged: false,
      retryable: false,
    }));
    await queue.enqueue(event("invalid-event", "GBPUSD"));
    await queue.drain();
    const snapshot = await queue.snapshot();
    expect(snapshot.pending).toBe(0);
    expect(snapshot.stats.rejected).toBe(1);
    expect(snapshot.stats.dropped).toBe(1);
    expect(snapshot.stats.byInstrument.GBPUSD.rejected).toBe(1);
  });

  it("acknowledges each queued event only once even when drain is duplicated", async () => {
    const deliver = vi.fn(async () => ({ acknowledged: true, retryable: false }));
    const queue = outbox(new MemoryStorage(), deliver);
    await queue.enqueue(event("event-1"));
    await Promise.all([queue.drain(), queue.drain()]);
    expect(deliver).toHaveBeenCalledTimes(1);
    expect((await queue.snapshot()).stats.acknowledged).toBe(1);
  });
});
