import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DecisionBoardJournalPanel } from "@/components/reports/decision-board-journal-panel";

describe("DecisionBoardJournalPanel", () => {
  it("renders missed/stale warnings without actions or local paths", () => {
    const html = renderToStaticMarkup(
      <DecisionBoardJournalPanel
        status={{
          state: "AVAILABLE",
          records: [
            {
              schema_version: "decision-board.v0",
              run_id: "entry-slot-001",
              run_kind: "ENTRY",
              status: "STALE_INCOMPLETE",
              expected_at: "2026-08-11T01:00:00Z",
              started_at: "2026-08-11T01:00:01Z",
              terminal_at: "2026-08-11T02:00:00Z",
              grace_seconds: 60,
              stale_seconds: 300,
              issues: [
                {
                  code: "STALE_INCOMPLETE",
                  message:
                    "Started run did not reach a terminal state before its TTL.",
                },
              ],
              report_file: null,
            },
          ],
        }}
      />,
    );

    expect(html).toContain("Local shadow run warning");
    expect(html).toContain("STALE_INCOMPLETE");
    expect(html).toContain("entry-slot-001");
    expect(html).not.toContain("DECISION_BOARD_JOURNAL_DIR");
    expect(html).not.toMatch(/order|notify|notification/i);
    expect(html).not.toContain("<button");
  });
});
