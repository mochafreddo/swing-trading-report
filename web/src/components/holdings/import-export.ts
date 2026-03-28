import type { HoldingsYamlImportResponse } from "@/lib/types";

import { readApiError } from "./helpers";

type Fetcher = typeof fetch;

interface HoldingsYamlExportPayload {
  filename: string;
  document: string;
}

function parseJsonText(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

function resolveFilename(contentDisposition: string | null): string {
  if (!contentDisposition) {
    return "holdings.yaml";
  }
  const match = contentDisposition.match(/filename="?([^";]+)"?/i);
  return match?.[1]?.trim() || "holdings.yaml";
}

export async function requestHoldingsYamlExport(
  fetcher: Fetcher = fetch,
): Promise<HoldingsYamlExportPayload> {
  const response = await fetcher("/api/holdings/yaml", {
    method: "GET",
    cache: "no-store",
  });
  const text = await response.text();
  if (!response.ok) {
    const payload = parseJsonText(text);
    throw new Error(
      readApiError(payload) || text || "Failed to export holdings.yaml",
    );
  }

  return {
    filename: resolveFilename(response.headers.get("content-disposition")),
    document: text,
  };
}

export async function requestHoldingsYamlImport(
  document: string,
  apply: boolean,
  fetcher: Fetcher = fetch,
): Promise<HoldingsYamlImportResponse> {
  const response = await fetcher("/api/holdings/yaml", {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      document,
      apply,
    }),
  });

  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    throw new Error(readApiError(payload) || "Failed to import holdings.yaml");
  }
  return payload as HoldingsYamlImportResponse;
}

export function triggerTextDownload(
  filename: string,
  textContent: string,
  mimeType = "application/yaml;charset=utf-8",
): void {
  const blob = new Blob([textContent], { type: mimeType });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}
