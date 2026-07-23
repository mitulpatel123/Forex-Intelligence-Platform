import { describe, expect, it, vi } from "vitest";
import {
  EMPTY_STATS,
  PersistentOutbox,
  type OutboxEvent,
  type StorageLike,
} from "../src/outbox";

class MemoryStorage implements StorageLike {
  values: Record<string, unknown> = {};

  async get(keys: string[]): Promise<Record<string, unknown>> {
    return Object.fromEntries(keys.map((key) => [key, this.values[key]]));
  }

  async set(items: Record<string, unknown>): Promise<void> {
    Object.assign(this.values, structuredClone(items));
  }
}

function event(id: string, now = 1_000): OutboxEvent {
  return {
    eventId: id,
    kind: "visible_quote",
    url: "http://127.0.0.1:8001/ingest/provider",
    body: { event_id: id },
    attempts: 0,
    nextAttemptAt: now,
  };
}

describe("persistent browser outbox", () => {
  it("persists a failed event and retries the same event until acknowledged", async () => {
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
    const schedule = vi.fn(async () => undefined);
    const outbox = new PersistentOutbox({
      maxSize: 10,
      storage,
      deliver,
      schedule,
      now: () => now,
    });

    expect(await outbox.enqueue(event("event-1"))).toBe(true);
    await outbox.drain();
    expect(await outbox.snapshot()).toEqual({
      pending: 1,
      stats: { ...EMPTY_STATS, produced: 1, retries: 1 },
    });

    now = 1_500;
    const restored = new PersistentOutbox({
      maxSize: 10,
      storage,
      deliver,
      schedule,
      now: () => now,
    });
    await restored.drain();
    expect(delivered).toEqual(["event-1", "event-1"]);
    expect(await restored.snapshot()).toEqual({
      pending: 0,
      stats: { ...EMPTY_STATS, produced: 1, retries: 1, acknowledged: 1 },
    });
  });

  it("bounds the queue and exposes explicit drops", async () => {
    const storage = new MemoryStorage();
    const outbox = new PersistentOutbox({
      maxSize: 1,
      storage,
      deliver: vi.fn(),
      schedule: vi.fn(async () => undefined),
      now: () => 1_000,
    });
    expect(await outbox.enqueue(event("event-1"))).toBe(true);
    expect(await outbox.enqueue(event("event-2"))).toBe(false);
    expect(await outbox.snapshot()).toEqual({
      pending: 1,
      stats: { ...EMPTY_STATS, produced: 2, dropped: 1 },
    });
  });

  it("removes permanent backend rejections and counts them", async () => {
    const storage = new MemoryStorage();
    const outbox = new PersistentOutbox({
      maxSize: 10,
      storage,
      deliver: vi.fn(async () => ({ acknowledged: false, retryable: false })),
      schedule: vi.fn(async () => undefined),
      now: () => 1_000,
    });
    await outbox.enqueue(event("invalid-event"));
    await outbox.drain();
    expect(await outbox.snapshot()).toEqual({
      pending: 0,
      stats: { ...EMPTY_STATS, produced: 1, dropped: 1, rejected: 1 },
    });
  });
});
