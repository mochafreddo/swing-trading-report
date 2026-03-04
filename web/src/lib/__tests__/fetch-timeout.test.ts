import { afterEach, describe, expect, it, vi } from "vitest";

import { FetchTimeoutError, fetchWithTimeout } from "@/lib/fetch-timeout";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("fetchWithTimeout", () => {
  it("wraps timeout-like errors into FetchTimeoutError", async () => {
    vi.stubEnv("SAB_EXTERNAL_FETCH_TIMEOUT_MS", "25");
    const timeoutError = Object.assign(
      new Error("The operation was aborted due to timeout"),
      {
        name: "TimeoutError",
      },
    );
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(timeoutError);

    await expect(
      fetchWithTimeout("https://example.com"),
    ).rejects.toBeInstanceOf(FetchTimeoutError);
  });

  it("wraps generic AbortError when timeout signal fired", async () => {
    vi.stubEnv("SAB_EXTERNAL_FETCH_TIMEOUT_MS", "1");
    vi.spyOn(globalThis, "fetch").mockImplementationOnce((_, init) => {
      return new Promise((_, reject) => {
        const signal = init?.signal as AbortSignal | undefined;
        if (!signal) {
          reject(new Error("signal is required"));
          return;
        }
        signal.addEventListener(
          "abort",
          () => {
            reject(
              Object.assign(new Error("This operation was aborted"), {
                name: "AbortError",
              }),
            );
          },
          { once: true },
        );
      });
    });

    await expect(
      fetchWithTimeout("https://example.com"),
    ).rejects.toBeInstanceOf(FetchTimeoutError);
  });

  it("respects caller abort signal when provided", async () => {
    vi.stubEnv("SAB_EXTERNAL_FETCH_TIMEOUT_MS", "50");
    vi.spyOn(globalThis, "fetch").mockImplementationOnce((_, init) => {
      return new Promise((_, reject) => {
        const signal = init?.signal as AbortSignal | undefined;
        if (!signal) {
          reject(new Error("signal is required"));
          return;
        }
        signal.addEventListener(
          "abort",
          () => {
            const reason = (
              signal as AbortSignal & {
                reason?: { name?: string; message?: string };
              }
            ).reason;
            reject(
              Object.assign(new Error(reason?.message ?? "aborted"), {
                name: reason?.name ?? "AbortError",
              }),
            );
          },
          { once: true },
        );
      });
    });

    const controller = new AbortController();
    const pending = fetchWithTimeout("https://example.com", {
      signal: controller.signal,
    } as unknown as RequestInit);
    controller.abort();

    await expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
  });

  it("keeps caller abort classification even when timeout fires later", async () => {
    vi.stubEnv("SAB_EXTERNAL_FETCH_TIMEOUT_MS", "5");
    vi.spyOn(globalThis, "fetch").mockImplementationOnce((_, init) => {
      return new Promise((_, reject) => {
        const signal = init?.signal as AbortSignal | undefined;
        if (!signal) {
          reject(new Error("signal is required"));
          return;
        }
        signal.addEventListener(
          "abort",
          () => {
            const reason = (
              signal as AbortSignal & {
                reason?: { name?: string; message?: string };
              }
            ).reason;
            setTimeout(() => {
              reject(
                Object.assign(new Error(reason?.message ?? "aborted"), {
                  name: reason?.name ?? "AbortError",
                }),
              );
            }, 20);
          },
          { once: true },
        );
      });
    });

    const controller = new AbortController();
    const pending = fetchWithTimeout("https://example.com", {
      signal: controller.signal,
    } as unknown as RequestInit);
    controller.abort(
      Object.assign(new Error("manual abort"), { name: "AbortError" }),
    );

    await expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});
