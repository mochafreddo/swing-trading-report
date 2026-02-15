import { Suspense } from "react";

import { ReportsClient } from "@/components/reports-client";

export default function ReportsPage() {
  return (
    <Suspense
      fallback={
        <section className="panel">
          <p className="subtle">Loading reports...</p>
        </section>
      }
    >
      <ReportsClient />
    </Suspense>
  );
}
