export function toErrorMessage(
  error: unknown,
  fallback: string = "Unknown error",
): string {
  return error instanceof Error ? error.message : fallback;
}
