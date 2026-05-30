import { readApiError } from "@/lib/error-utils";

type Fetcher = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export async function requestLogout(fetcher: Fetcher = fetch): Promise<void> {
  const response = await fetcher("/api/auth/logout", { method: "POST" });
  if (response.ok) {
    return;
  }

  let payload: unknown = null;
  try {
    payload = (await response.json()) as unknown;
  } catch {
    payload = null;
  }
  throw new Error(readApiError(payload) || "Sign out failed");
}
