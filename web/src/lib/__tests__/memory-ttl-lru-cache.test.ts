import { describe, expect, it, vi } from "vitest";

import { createMemoryTtlLruCache } from "@/lib/memory-ttl-lru-cache";

describe("createMemoryTtlLruCache", () => {
  it("returns cached value before TTL expiration", async () => {
    let nowMs = 1000;
    const cache = createMemoryTtlLruCache<number>({
      maxEntries: 10,
      now: () => nowMs,
    });
    const loader = vi.fn(async () => 7);

    await expect(
      cache.getOrLoad({
        key: "alpha",
        ttlMs: 100,
        load: loader,
      }),
    ).resolves.toBe(7);

    nowMs += 50;

    await expect(
      cache.getOrLoad({
        key: "alpha",
        ttlMs: 100,
        load: loader,
      }),
    ).resolves.toBe(7);

    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("caches null values as valid payloads", async () => {
    const cache = createMemoryTtlLruCache<number | null>({
      maxEntries: 10,
    });
    const loader = vi.fn(async () => null);

    await expect(
      cache.getOrLoad({
        key: "nullable",
        ttlMs: 1000,
        load: loader,
      }),
    ).resolves.toBeNull();
    await expect(
      cache.getOrLoad({
        key: "nullable",
        ttlMs: 1000,
        load: loader,
      }),
    ).resolves.toBeNull();

    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("reloads value after TTL expiration", async () => {
    let nowMs = 2000;
    const cache = createMemoryTtlLruCache<number>({
      maxEntries: 10,
      now: () => nowMs,
    });
    const loader = vi.fn(async () => 11);

    await cache.getOrLoad({
      key: "beta",
      ttlMs: 100,
      load: loader,
    });

    nowMs += 150;

    await cache.getOrLoad({
      key: "beta",
      ttlMs: 100,
      load: loader,
    });

    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("deduplicates in-flight loads for same key", async () => {
    const cache = createMemoryTtlLruCache<number>({
      maxEntries: 10,
    });
    let resolve: ((value: number) => void) | undefined;
    const loader = vi.fn(
      () =>
        new Promise<number>((innerResolve) => {
          resolve = innerResolve;
        }),
    );

    const promiseA = cache.getOrLoad({
      key: "gamma",
      ttlMs: 1000,
      load: loader,
    });
    const promiseB = cache.getOrLoad({
      key: "gamma",
      ttlMs: 1000,
      load: loader,
    });

    expect(loader).toHaveBeenCalledTimes(1);
    resolve?.(23);

    await expect(promiseA).resolves.toBe(23);
    await expect(promiseB).resolves.toBe(23);
  });

  it("evicts least-recently-used key when maxEntries exceeded", async () => {
    const cache = createMemoryTtlLruCache<number>({
      maxEntries: 2,
    });
    const loader = vi.fn(async (key: string) => {
      if (key === "a") {
        return 1;
      }
      if (key === "b") {
        return 2;
      }
      if (key === "c") {
        return 3;
      }
      return 4;
    });

    await cache.getOrLoad({
      key: "a",
      ttlMs: 1000,
      load: () => loader("a"),
    });
    await cache.getOrLoad({
      key: "b",
      ttlMs: 1000,
      load: () => loader("b"),
    });
    await cache.getOrLoad({
      key: "a",
      ttlMs: 1000,
      load: () => loader("a"),
    });
    await cache.getOrLoad({
      key: "c",
      ttlMs: 1000,
      load: () => loader("c"),
    });
    await cache.getOrLoad({
      key: "b",
      ttlMs: 1000,
      load: () => loader("b"),
    });

    expect(loader).toHaveBeenCalledTimes(4);
  });

  it("bypasses cache on refresh=true", async () => {
    const cache = createMemoryTtlLruCache<number>({
      maxEntries: 10,
    });
    const loader = vi
      .fn<() => Promise<number>>()
      .mockResolvedValueOnce(31)
      .mockResolvedValueOnce(32);

    await expect(
      cache.getOrLoad({
        key: "delta",
        ttlMs: 1000,
        load: loader,
      }),
    ).resolves.toBe(31);
    await expect(
      cache.getOrLoad({
        key: "delta",
        ttlMs: 1000,
        refresh: true,
        load: loader,
      }),
    ).resolves.toBe(32);

    expect(loader).toHaveBeenCalledTimes(2);
  });
});
