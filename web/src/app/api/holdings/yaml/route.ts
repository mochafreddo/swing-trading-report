import { NextRequest } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import {
  elapsedMs,
  getApiRequestId,
  logApiError,
  logApiInfo,
  logApiWarn,
  withApiRequestId,
  type ApiLogFields,
} from "@/lib/api-request-log";
import {
  buildHoldingsYamlDocument,
  buildHoldingsYamlImportSummary,
  HoldingsYamlError,
  MAX_HOLDINGS_YAML_DOCUMENT_BYTES,
  parseHoldingsYamlDocument,
} from "@/lib/holdings-yaml";
import { parseJsonBody } from "@/lib/parse-json-body";
import { jsonWithNoStore } from "@/lib/reports-response";
import { holdingYamlImportRequestSchema } from "@/lib/schemas";
import { fetchAllHoldings, replaceAllHoldings } from "@/lib/supabase-admin";
import type { HoldingsYamlImportResponse } from "@/lib/types";

import {
  holdingsDependency,
  holdingsJsonError,
  holdingsStatusCode,
} from "../holding-api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/holdings/yaml";
const YAML_IMPORT_JSON_BODY_MAX_BYTES =
  MAX_HOLDINGS_YAML_DOCUMENT_BYTES * 2 + 16 * 1024;

function logRejectedYamlRequest(
  requestId: string,
  startedAtMs: number,
  method: "GET" | "POST",
  operation: string,
  statusCode: number,
  reason: string,
  fields: ApiLogFields = {},
): void {
  logApiWarn({
    event: "web_api_request_rejected",
    request_id: requestId,
    route: ROUTE,
    method,
    operation,
    status: "failed",
    status_code: statusCode,
    reason,
    duration_ms: elapsedMs(startedAtMs),
    ...fields,
  });
}

export async function GET(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();
  const method = "GET";
  const operation = "export_holdings_yaml";

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedYamlRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  try {
    const holdings = await fetchAllHoldings();
    const document = buildHoldingsYamlDocument(holdings);
    const response = new Response(document, {
      status: 200,
      headers: {
        "Content-Type": "application/yaml; charset=utf-8",
        "Content-Disposition": 'attachment; filename="holdings.yaml"',
        "Cache-Control": "private, no-store, max-age=0, must-revalidate",
      },
    });
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "success",
      status_code: 200,
      dependency: "supabase",
      duration_ms: elapsedMs(startedAtMs),
      holding_count: holdings.length,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    const statusCode = holdingsStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "failed",
      status_code: statusCode,
      dependency: holdingsDependency(error),
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
    });
    return withApiRequestId(holdingsJsonError(error), requestId);
  }
}

export async function POST(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();
  const method = "POST";
  const operation = "import_holdings_yaml";

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedYamlRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  const body = await parseJsonBody(request, {
    maxBytes: YAML_IMPORT_JSON_BODY_MAX_BYTES,
  });
  if (!body.ok) {
    logRejectedYamlRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      body.response.status,
      "invalid_json",
    );
    return withApiRequestId(body.response, requestId);
  }

  const parsedRequest = holdingYamlImportRequestSchema.safeParse(body.payload);
  if (!parsedRequest.success) {
    logRejectedYamlRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      400,
      "invalid_payload",
    );
    return withApiRequestId(
      jsonWithNoStore(
        {
          error: "Invalid holdings YAML import payload",
          details: parsedRequest.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const importedHoldings = parseHoldingsYamlDocument(
      parsedRequest.data.document,
    );
    const currentHoldings = await fetchAllHoldings();
    const summary = buildHoldingsYamlImportSummary(
      currentHoldings,
      importedHoldings,
    );

    if (parsedRequest.data.apply) {
      const hasChanges =
        summary.createCount > 0 ||
        summary.updateCount > 0 ||
        summary.deleteCount > 0;
      if (hasChanges) {
        const result = await replaceAllHoldings(importedHoldings, {
          expectedCurrentHoldings: currentHoldings,
        });
        const appliedResponse: HoldingsYamlImportResponse = {
          mode: "apply",
          summary: {
            ...summary,
            createCount: result.insertedCount,
            updateCount: result.updatedCount,
            deleteCount: result.deletedCount,
            unchangedCount: result.unchangedCount,
          },
        };
        const response = jsonWithNoStore(appliedResponse);
        logApiInfo({
          event: "web_api_request_completed",
          request_id: requestId,
          route: ROUTE,
          method,
          operation,
          status: "success",
          status_code: 200,
          dependency: "supabase",
          duration_ms: elapsedMs(startedAtMs),
          mode: "apply",
          create_count: result.insertedCount,
          update_count: result.updatedCount,
          delete_count: result.deletedCount,
          unchanged_count: result.unchangedCount,
        });
        return withApiRequestId(response, requestId);
      }
    }

    const responsePayload: HoldingsYamlImportResponse = {
      mode: parsedRequest.data.apply ? "apply" : "dry-run",
      summary,
    };
    const response = jsonWithNoStore(responsePayload);
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "success",
      status_code: 200,
      dependency: "supabase",
      duration_ms: elapsedMs(startedAtMs),
      mode: responsePayload.mode,
      create_count: summary.createCount,
      update_count: summary.updateCount,
      delete_count: summary.deleteCount,
      unchanged_count: summary.unchangedCount,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    if (error instanceof HoldingsYamlError) {
      logRejectedYamlRequest(
        requestId,
        startedAtMs,
        method,
        operation,
        400,
        "invalid_yaml",
      );
      return withApiRequestId(
        jsonWithNoStore({ error: error.message }, { status: 400 }),
        requestId,
      );
    }
    const statusCode = holdingsStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "failed",
      status_code: statusCode,
      dependency: holdingsDependency(error),
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
      mode: parsedRequest.data.apply ? "apply" : "dry-run",
    });
    return withApiRequestId(holdingsJsonError(error), requestId);
  }
}
