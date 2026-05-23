import { useCallback, useState } from "react";

import {
  requestHoldingsYamlExport,
  requestHoldingsYamlImport,
  triggerTextDownload,
} from "@/components/holdings/import-export";
import type {
  HoldingsYamlImportResponse,
  HoldingsYamlImportSummary,
} from "@/lib/types";

type ExportRequest = typeof requestHoldingsYamlExport;
type ImportRequest = typeof requestHoldingsYamlImport;
type TriggerDownload = typeof triggerTextDownload;

interface UseHoldingsImportOptions {
  refresh: () => Promise<void>;
  cancelEdit: () => void;
  cancelAddBuy: () => void;
  requestExport?: ExportRequest;
  requestImport?: ImportRequest;
  triggerDownload?: TriggerDownload;
  confirm?: (message: string) => boolean;
}

function formatImportSuccessMessage(
  summary: HoldingsYamlImportSummary,
): string {
  if (
    summary.createCount === 0 &&
    summary.updateCount === 0 &&
    summary.deleteCount === 0
  ) {
    return "변경 사항이 없어 holdings import를 적용하지 않았습니다.";
  }

  return `적용 완료: create ${summary.createCount}, update ${summary.updateCount}, delete ${summary.deleteCount}`;
}

export function useHoldingsImport({
  refresh,
  cancelEdit,
  cancelAddBuy,
  requestExport = requestHoldingsYamlExport,
  requestImport = requestHoldingsYamlImport,
  triggerDownload = triggerTextDownload,
  confirm = (message) => window.confirm(message),
}: UseHoldingsImportOptions) {
  const [exporting, setExporting] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [document, setDocument] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [summary, setSummary] = useState<HoldingsYamlImportSummary | null>(
    null,
  );

  const handleExport = useCallback(async () => {
    setExporting(true);
    setError(null);
    setSuccess(null);
    try {
      const payload = await requestExport();
      triggerDownload(payload.filename, payload.document);
    } catch (exportError) {
      setError(
        exportError instanceof Error
          ? exportError.message
          : "Failed to export holdings.yaml",
      );
    } finally {
      setExporting(false);
    }
  }, [requestExport, triggerDownload]);

  const handleFileSelected = useCallback(async (file: File | null) => {
    if (!file) {
      setFileName(null);
      setDocument(null);
      setSummary(null);
      setError(null);
      setSuccess(null);
      return;
    }

    try {
      const text = await file.text();
      setFileName(file.name);
      setDocument(text);
      setSummary(null);
      setError(null);
      setSuccess(null);
    } catch (readError) {
      setFileName(null);
      setDocument(null);
      setSummary(null);
      setSuccess(null);
      setError(
        readError instanceof Error
          ? readError.message
          : "Failed to read selected file",
      );
    }
  }, []);

  const runImport = useCallback(
    async (apply: boolean): Promise<HoldingsYamlImportResponse | null> => {
      if (!document) {
        setError("Import할 holdings.yaml 파일을 먼저 선택하세요.");
        return null;
      }
      if (apply && !summary) {
        setError("먼저 dry-run을 실행하세요.");
        return null;
      }
      if (
        apply &&
        !confirm(
          "현재 holdings DB를 업로드한 파일 내용으로 교체합니다. 계속하시겠습니까?",
        )
      ) {
        return null;
      }

      if (apply) {
        setApplying(true);
      } else {
        setLoading(true);
      }
      setError(null);
      setSuccess(null);
      try {
        const response = await requestImport(document, apply);
        setSummary(response.summary);
        if (apply) {
          cancelEdit();
          cancelAddBuy();
          setSuccess(formatImportSuccessMessage(response.summary));
          setDocument(null);
          setFileName(null);
          await refresh();
        }
        return response;
      } catch (importError) {
        setError(
          importError instanceof Error
            ? importError.message
            : "Failed to import holdings.yaml",
        );
        return null;
      } finally {
        if (apply) {
          setApplying(false);
        } else {
          setLoading(false);
        }
      }
    },
    [
      cancelAddBuy,
      cancelEdit,
      confirm,
      document,
      refresh,
      requestImport,
      summary,
    ],
  );

  return {
    exporting,
    fileName,
    loading,
    applying,
    error,
    success,
    summary,
    canDryRun: Boolean(document),
    canApply: Boolean(document && summary),
    handleExport,
    handleFileSelected,
    dryRun: async () => {
      await runImport(false);
    },
    apply: async () => {
      await runImport(true);
    },
  };
}
