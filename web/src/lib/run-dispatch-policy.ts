import type { Provider, ScanUniverse } from "@/lib/types";

export const SCAN_PROVIDER_UNIVERSE_POLICY = {
  kis: ["KR", "US", "both"],
  pykrx: ["KR"],
} as const satisfies Record<Provider, readonly ScanUniverse[]>;

const DEFAULT_SCAN_UNIVERSE_BY_PROVIDER: Readonly<
  Record<Provider, ScanUniverse>
> = {
  kis: "both",
  pykrx: "KR",
};

export const PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE =
  "provider=pykrx supports only universe=KR";

type AllowedScanUniverse<P extends Provider> =
  (typeof SCAN_PROVIDER_UNIVERSE_POLICY)[P][number];

export function isScanUniverseAllowed<P extends Provider>(
  provider: P,
  universe: ScanUniverse,
): universe is AllowedScanUniverse<P> {
  const allowedUniverses = SCAN_PROVIDER_UNIVERSE_POLICY[
    provider
  ] as readonly ScanUniverse[];
  return allowedUniverses.includes(universe);
}

export function coerceScanUniverseForProvider(
  provider: Provider,
  universe: ScanUniverse,
): ScanUniverse {
  if (isScanUniverseAllowed(provider, universe)) {
    return universe;
  }
  return DEFAULT_SCAN_UNIVERSE_BY_PROVIDER[provider];
}
