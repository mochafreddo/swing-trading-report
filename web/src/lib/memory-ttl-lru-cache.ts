export interface MemoryTtlLruCacheOptions {
  maxEntries: number;
  now?: () => number;
}

export interface MemoryTtlLruLoadOptions<T> {
  key: string;
  ttlMs: number;
  refresh?: boolean;
  load: () => Promise<T>;
}

interface CacheEntry<T> {
  value: T;
  expiresAt: number;
}

export interface MemoryTtlLruCache<T> {
  getOrLoad(options: MemoryTtlLruLoadOptions<T>): Promise<T>;
  clear(): void;
}

export function createMemoryTtlLruCache<T>(
  options: MemoryTtlLruCacheOptions,
): MemoryTtlLruCache<T> {
  const maxEntries = Math.max(1, Math.trunc(options.maxEntries));
  const now = options.now ?? Date.now;
  const values = new Map<string, CacheEntry<T>>();
  const inFlight = new Map<string, Promise<T>>();

  function evictExpiredEntry(key: string): void {
    const existing = values.get(key);
    if (!existing) {
      return;
    }
    if (existing.expiresAt <= now()) {
      values.delete(key);
    }
  }

  function getCachedValue(key: string): T | null {
    evictExpiredEntry(key);
    const existing = values.get(key);
    if (!existing) {
      return null;
    }
    values.delete(key);
    values.set(key, existing);
    return existing.value;
  }

  function setCachedValue(key: string, value: T, ttlMs: number): void {
    if (ttlMs <= 0) {
      return;
    }
    const entry: CacheEntry<T> = {
      value,
      expiresAt: now() + ttlMs,
    };
    values.delete(key);
    values.set(key, entry);
    while (values.size > maxEntries) {
      const oldestKey = values.keys().next().value;
      if (typeof oldestKey !== "string") {
        break;
      }
      values.delete(oldestKey);
    }
  }

  return {
    async getOrLoad(loadOptions: MemoryTtlLruLoadOptions<T>): Promise<T> {
      const { key, ttlMs, refresh, load } = loadOptions;
      if (!refresh) {
        const cachedValue = getCachedValue(key);
        if (cachedValue !== null) {
          return cachedValue;
        }
        const pending = inFlight.get(key);
        if (pending) {
          return pending;
        }
      }

      const task = (async () => {
        const loaded = await load();
        setCachedValue(key, loaded, ttlMs);
        return loaded;
      })();

      if (!refresh) {
        inFlight.set(key, task);
      }

      try {
        return await task;
      } finally {
        if (!refresh) {
          inFlight.delete(key);
        }
      }
    },
    clear(): void {
      values.clear();
      inFlight.clear();
    },
  };
}
