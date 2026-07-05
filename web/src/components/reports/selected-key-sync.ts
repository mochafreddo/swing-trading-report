interface ResolveSelectedKeyFromUrlInput {
  previousSelectedKey: string | null;
  nextKeyRaw: string | null;
  availableKeys?: readonly string[];
  preserveSelectionWhenKeyMissing?: boolean;
}

export function resolveSelectedKeyFromUrl({
  previousSelectedKey,
  nextKeyRaw,
  preserveSelectionWhenKeyMissing = false,
}: ResolveSelectedKeyFromUrlInput): string | null {
  const nextKey = nextKeyRaw?.trim() || null;
  if (!nextKey) {
    return preserveSelectionWhenKeyMissing ? previousSelectedKey : null;
  }
  return previousSelectedKey === nextKey ? previousSelectedKey : nextKey;
}
