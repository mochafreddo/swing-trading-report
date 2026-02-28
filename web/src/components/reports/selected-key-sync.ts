interface ResolveSelectedKeyFromUrlInput {
  previousSelectedKey: string | null;
  nextKeyRaw: string | null;
}

export function resolveSelectedKeyFromUrl({
  previousSelectedKey,
  nextKeyRaw,
}: ResolveSelectedKeyFromUrlInput): string | null {
  const nextKey = nextKeyRaw?.trim() || null;
  if (!nextKey) {
    return previousSelectedKey;
  }
  return previousSelectedKey === nextKey ? previousSelectedKey : nextKey;
}
