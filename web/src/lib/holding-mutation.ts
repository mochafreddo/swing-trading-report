const hasOwn = (value: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

export function normalizeHoldingMutationForPersistence<T extends object>(
  input: T,
): T & { entry_pattern?: string | null } {
  const output = { ...input } as Record<string, unknown>;
  const ownsQuantity = hasOwn(input, "quantity");
  const ownsEntryPattern = hasOwn(input, "entry_pattern");
  const quantityValue = ownsQuantity ? output.quantity : undefined;
  const quantity =
    typeof quantityValue === "number" && Number.isFinite(quantityValue)
      ? quantityValue
      : null;

  if (ownsEntryPattern && output.entry_pattern === undefined) {
    delete output.entry_pattern;
  }

  if (quantity === 0) {
    output.entry_pattern = null;
    return output as T & { entry_pattern?: string | null };
  }

  if (
    ownsEntryPattern &&
    output.entry_pattern !== undefined &&
    output.entry_pattern !== null &&
    (quantity === null || quantity <= 0)
  ) {
    throw new Error("entry_pattern requires quantity > 0");
  }

  return output as T & { entry_pattern?: string | null };
}
