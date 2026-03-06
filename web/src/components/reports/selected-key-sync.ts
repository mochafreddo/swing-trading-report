interface ResolveSelectedKeyFromUrlInput {
  previousSelectedKey: string | null;
  nextKeyRaw: string | null;
  availableKeys: readonly string[];
  preserveSelectionWhenKeyMissing?: boolean;
}

export function resolveSelectedKeyFromUrl({
  previousSelectedKey,
  nextKeyRaw,
  availableKeys,
  preserveSelectionWhenKeyMissing = false,
}: ResolveSelectedKeyFromUrlInput): string | null {
  const nextKey = nextKeyRaw?.trim() || null;
  if (!nextKey) {
    return preserveSelectionWhenKeyMissing ? previousSelectedKey : null;
  }
  if (
    availableKeys.length > 0 &&
    !availableKeys.some((candidateKey) => candidateKey === nextKey)
  ) {
    return previousSelectedKey;
  }
  return previousSelectedKey === nextKey ? previousSelectedKey : nextKey;
}
