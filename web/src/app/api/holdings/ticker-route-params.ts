export type CatchAllTickerRouteContext = {
  params:
    | { ticker: string[] }
    | Promise<{
        ticker: string[];
      }>;
};

export function joinTickerPath(segments: string[]): string {
  return segments.join("/");
}
