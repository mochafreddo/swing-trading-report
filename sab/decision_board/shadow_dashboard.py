"""Portable dashboard artifact model for one shadow evaluation snapshot."""

from __future__ import annotations

from typing import Any


def _metric_row(name: str, metric: dict[str, object]) -> dict[str, object]:
    return {
        "metric": name,
        "value": metric["value"],
        "numerator": metric["numerator"],
        "denominator": metric["denominator"],
        "threshold": metric["threshold"],
        "threshold_status": metric["threshold_status"],
    }


def build_shadow_dashboard_artifact_v0(
    evaluation: dict[str, object],
) -> dict[str, object]:
    """Build a canonical Data Analytics dashboard artifact payload."""

    if evaluation.get("schema_version") != "decision-board-shadow-evaluation.v0":
        raise ValueError("shadow evaluation schema is invalid")
    generated_at = evaluation["generated_at"]
    progress = evaluation["progress"]
    quality = evaluation["quality"]
    slots = evaluation["slots"]
    provider_metrics = evaluation["provider_metrics"]
    lane_quality = evaluation["lane_quality"]
    hard_metrics = evaluation["hard_metrics"]
    cases = evaluation["cases"]
    if (
        type(generated_at) is not str
        or type(progress) is not dict
        or type(quality) is not dict
        or type(slots) is not list
        or type(provider_metrics) is not list
        or type(lane_quality) is not list
        or type(hard_metrics) is not dict
        or type(cases) is not list
    ):
        raise ValueError("shadow evaluation shape is invalid")

    quality_rows = sorted(
        [
            _metric_row("Provider failure rate", quality["provider_failure_rate"]),
            _metric_row("Research coverage rate", quality["research_coverage_rate"]),
            _metric_row("Fresh source rate", quality["fresh_source_rate"]),
        ],
        key=lambda row: str(row["metric"]),
    )
    dashboard_slots = [
        {
            **row,
            "issue_codes": ", ".join(str(code) for code in row["issue_codes"]),
            "published_action_counts": ", ".join(
                f"{action}={count}"
                for action, count in row["published_action_counts"].items()
            ),
            "provider_counts": "; ".join(
                (
                    f"{provider}: attempts={counts['attempts']}, "
                    f"failures={counts['failures']}, timeouts={counts['timeouts']}"
                )
                for provider, counts in row["provider_counts"].items()
            ),
        }
        for row in slots
    ]
    dashboard_cases = sorted(
        [
            {
                **row,
                "expected_actions": ", ".join(
                    str(action) for action in row["expected_actions"]
                ),
                "issue_codes": ", ".join(str(code) for code in row["issue_codes"]),
            }
            for row in cases
        ],
        key=lambda row: (
            str(row["ticker"]),
            str(row["session"]),
            str(row["lane"]),
            str(row["run_id"]),
        ),
    )
    dashboard_provider_metrics = sorted(
        provider_metrics,
        key=lambda row: (str(row["lane"]), str(row["provider"])),
    )
    dashboard_lane_quality = sorted(lane_quality, key=lambda row: str(row["lane"]))
    hard_metric_rows = [
        {"metric": name, "value": value} for name, value in sorted(hard_metrics.items())
    ]
    summary = [
        {
            "terminal_slots": progress["terminal_slots"],
            "planned_slots": progress["planned_slots"],
            "completed_sessions": progress["completed_sessions"],
            "planned_sessions": progress["planned_sessions"],
            "due_terminal_coverage": progress["due_terminal_coverage"],
            "provider_failure_rate": quality["provider_failure_rate"]["value"],
            "research_coverage_rate": quality["research_coverage_rate"]["value"],
            "fresh_source_rate": quality["fresh_source_rate"]["value"],
            "unexplained_diffs": hard_metrics["unexplained"],
            "gate_state": progress["gate_state"],
        }
    ]
    source_queries = {
        "summary_source": """
SELECT
  json_extract(:evaluation_json, '$.progress.terminal_slots') AS terminal_slots,
  json_extract(:evaluation_json, '$.progress.planned_slots') AS planned_slots,
  json_extract(:evaluation_json, '$.progress.completed_sessions') AS completed_sessions,
  json_extract(:evaluation_json, '$.progress.planned_sessions') AS planned_sessions,
  json_extract(:evaluation_json, '$.progress.due_terminal_coverage') AS due_terminal_coverage,
  json_extract(:evaluation_json, '$.quality.provider_failure_rate.value') AS provider_failure_rate,
  json_extract(:evaluation_json, '$.quality.research_coverage_rate.value') AS research_coverage_rate,
  json_extract(:evaluation_json, '$.quality.fresh_source_rate.value') AS fresh_source_rate,
  json_extract(:evaluation_json, '$.hard_metrics.unexplained') AS unexplained_diffs,
  json_extract(:evaluation_json, '$.progress.gate_state') AS gate_state
""".strip(),
        "quality_source": """
WITH metrics(metric, path) AS (
  VALUES
    ('Provider failure rate', '$.quality.provider_failure_rate'),
    ('Research coverage rate', '$.quality.research_coverage_rate'),
    ('Fresh source rate', '$.quality.fresh_source_rate')
)
SELECT
  metric,
  json_extract(:evaluation_json, path || '.value') AS value,
  json_extract(:evaluation_json, path || '.numerator') AS numerator,
  json_extract(:evaluation_json, path || '.denominator') AS denominator,
  json_extract(:evaluation_json, path || '.threshold') AS threshold,
  json_extract(:evaluation_json, path || '.threshold_status') AS threshold_status
FROM metrics
ORDER BY metric
""".strip(),
        "provider_source": """
SELECT
  json_extract(value, '$.lane') AS lane,
  json_extract(value, '$.provider') AS provider,
  json_extract(value, '$.attempts') AS attempts,
  json_extract(value, '$.failures') AS failures,
  json_extract(value, '$.timeouts') AS timeouts,
  json_extract(value, '$.failure_rate') AS failure_rate,
  json_extract(value, '$.threshold_status') AS threshold_status
FROM json_each(:evaluation_json, '$.provider_metrics')
ORDER BY lane, provider
""".strip(),
        "lane_quality_source": """
SELECT
  json_extract(value, '$.lane') AS lane,
  json_extract(value, '$.research_coverage_numerator') AS research_coverage_numerator,
  json_extract(value, '$.research_coverage_denominator') AS research_coverage_denominator,
  json_extract(value, '$.research_coverage_rate') AS research_coverage_rate,
  json_extract(value, '$.research_coverage_threshold_status') AS research_coverage_threshold_status,
  json_extract(value, '$.fresh_source_numerator') AS fresh_source_numerator,
  json_extract(value, '$.fresh_source_denominator') AS fresh_source_denominator,
  json_extract(value, '$.fresh_source_rate') AS fresh_source_rate,
  json_extract(value, '$.fresh_source_threshold_status') AS fresh_source_threshold_status
FROM json_each(:evaluation_json, '$.lane_quality')
ORDER BY lane
""".strip(),
        "slots_source": """
SELECT
  json_extract(value, '$.session') AS session,
  json_extract(value, '$.lane') AS lane,
  json_extract(value, '$.expected_at') AS expected_at,
  json_extract(value, '$.slot_state') AS slot_state,
  json_extract(value, '$.journal_status') AS journal_status,
  json_extract(value, '$.publication_contract') AS publication_contract,
  json_extract(value, '$.expectation') AS expectation,
  json_extract(value, '$.diff_reason') AS diff_reason,
  json_extract(value, '$.eligible_count') AS eligible_count,
  json_extract(value, '$.research_attempted_count') AS research_attempted_count,
  json_extract(value, '$.research_succeeded_count') AS research_succeeded_count,
  json_extract(value, '$.research_timed_out_count') AS research_timed_out_count,
  json_extract(value, '$.published_item_count') AS published_item_count,
  json_extract(value, '$.verified_evidence_count') AS verified_evidence_count,
  json_extract(value, '$.fresh_verified_source_count') AS fresh_verified_source_count,
  json_extract(value, '$.run_id') AS run_id
FROM json_each(:evaluation_json, '$.slots')
ORDER BY expected_at
""".strip(),
        "cases_source": """
SELECT
  json_extract(value, '$.session') AS session,
  json_extract(value, '$.lane') AS lane,
  json_extract(value, '$.ticker') AS ticker,
  json_extract(value, '$.actual_action') AS actual_action,
  json_extract(value, '$.expectation') AS expectation,
  json_extract(value, '$.diff_reason') AS diff_reason,
  json_extract(value, '$.verified_evidence_count') AS verified_evidence_count,
  json_extract(value, '$.run_id') AS run_id
FROM json_each(:evaluation_json, '$.cases')
ORDER BY ticker, session, lane, run_id
""".strip(),
        "hard_metrics_source": """
SELECT
  key AS metric,
  value
FROM json_each(:evaluation_json, '$.hard_metrics')
ORDER BY metric
""".strip(),
    }
    sources = [
        {
            "id": source_id,
            "label": source_id.replace("_", " ").title(),
            "query": {
                "engine": "sqlite-json1",
                "language": "sql",
                "sql": query,
                "description": (
                    "Derives this bounded dashboard dataset from the validated "
                    "decision-board-shadow-evaluation.v0 JSON bound as "
                    ":evaluation_json."
                ),
                "executed_at": generated_at,
                "filters": [
                    "The Python evaluator includes only exact approved gate slots.",
                    "Future slots remain scheduled until their grace deadline.",
                ],
                "metric_definitions": [
                    "Due terminal coverage = due terminal slots / due slots.",
                    "Provider failure rate = provider failures / provider attempts.",
                    "Research coverage = eligible items with verified evidence / eligible items.",
                    "Fresh source rate = WITHIN_POLICY evidence / verified evidence.",
                    "Every unclassified frozen-action difference is UNEXPLAINED.",
                ],
            },
        }
        for source_id, query in source_queries.items()
    ]

    artifact: dict[str, Any] = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Decision Board shadow gate monitor",
            "description": (
                "Read-only progress, quality, and expectation reconciliation for the "
                "approved US SWING shadow gate."
            ),
            "generatedAt": generated_at,
            "filters": [
                {
                    "id": "lane_filter",
                    "label": "Lane",
                    "dataset": "slots",
                    "field": "lane",
                    "includeAll": True,
                    "targets": [
                        {"dataset": "provider_metrics", "field": "lane"},
                        {"dataset": "lane_quality", "field": "lane"},
                        {"dataset": "cases", "field": "lane"},
                    ],
                }
            ],
            "cards": [
                {
                    "id": "terminal_slots",
                    "dataset": "summary",
                    "sourceId": "summary_source",
                    "description": "Terminal slots across the frozen 40-slot plan.",
                    "metrics": [
                        {
                            "label": "Terminal slots",
                            "field": "terminal_slots",
                            "format": "number",
                        },
                        {
                            "label": "Planned",
                            "field": "planned_slots",
                            "format": "number",
                        },
                    ],
                },
                {
                    "id": "completed_sessions",
                    "dataset": "summary",
                    "sourceId": "summary_source",
                    "description": "Sessions with both ENTRY and HOLDING terminal.",
                    "metrics": [
                        {
                            "label": "Completed sessions",
                            "field": "completed_sessions",
                            "format": "number",
                        },
                        {
                            "label": "Required",
                            "field": "planned_sessions",
                            "format": "number",
                        },
                    ],
                },
                {
                    "id": "due_coverage",
                    "dataset": "summary",
                    "sourceId": "summary_source",
                    "description": "Terminal coverage for slots whose grace deadline passed.",
                    "metrics": [
                        {
                            "label": "Due terminal coverage",
                            "field": "due_terminal_coverage",
                            "format": "percent",
                        }
                    ],
                },
                {
                    "id": "provider_failure",
                    "dataset": "summary",
                    "sourceId": "summary_source",
                    "description": "Provider failures divided by provider attempts.",
                    "metrics": [
                        {
                            "label": "Provider failure rate",
                            "field": "provider_failure_rate",
                            "format": "percent",
                        }
                    ],
                },
                {
                    "id": "research_coverage",
                    "dataset": "summary",
                    "sourceId": "summary_source",
                    "description": "Eligible items with verified evidence.",
                    "metrics": [
                        {
                            "label": "Research coverage",
                            "field": "research_coverage_rate",
                            "format": "percent",
                        }
                    ],
                },
                {
                    "id": "unexplained_diffs",
                    "dataset": "summary",
                    "sourceId": "summary_source",
                    "description": "Differences without an approved classification.",
                    "metrics": [
                        {
                            "label": "Unexplained diffs",
                            "field": "unexplained_diffs",
                            "format": "number",
                        }
                    ],
                },
                {
                    "id": "fresh_sources",
                    "dataset": "summary",
                    "sourceId": "summary_source",
                    "description": "Verified evidence within the approved freshness policy.",
                    "metrics": [
                        {
                            "label": "Fresh source rate",
                            "field": "fresh_source_rate",
                            "format": "percent",
                        }
                    ],
                },
            ],
            "tables": [
                {
                    "id": "quality_table",
                    "title": "Quality thresholds",
                    "dataset": "quality",
                    "sourceId": "quality_source",
                    "defaultSort": {"field": "metric", "direction": "asc"},
                    "columns": [
                        {"field": "metric", "label": "Metric"},
                        {"field": "value", "label": "Observed", "format": "percent"},
                        {
                            "field": "threshold",
                            "label": "Threshold",
                            "format": "percent",
                        },
                        {"field": "threshold_status", "label": "Status"},
                        {
                            "field": "numerator",
                            "label": "Numerator",
                            "format": "number",
                        },
                        {
                            "field": "denominator",
                            "label": "Denominator",
                            "format": "number",
                        },
                    ],
                },
                {
                    "id": "provider_table",
                    "title": "Provider health by lane",
                    "dataset": "provider_metrics",
                    "sourceId": "provider_source",
                    "defaultSort": {"field": "attempts", "direction": "desc"},
                    "columns": [
                        {"field": "lane", "label": "Lane"},
                        {"field": "provider", "label": "Provider"},
                        {"field": "attempts", "label": "Attempts", "format": "number"},
                        {"field": "failures", "label": "Failures", "format": "number"},
                        {"field": "timeouts", "label": "Timeouts", "format": "number"},
                        {
                            "field": "failure_rate",
                            "label": "Failure rate",
                            "format": "percent",
                        },
                        {"field": "threshold_status", "label": "Status"},
                    ],
                },
                {
                    "id": "lane_quality_table",
                    "title": "Research quality by lane",
                    "dataset": "lane_quality",
                    "sourceId": "lane_quality_source",
                    "defaultSort": {"field": "lane", "direction": "asc"},
                    "columns": [
                        {"field": "lane", "label": "Lane"},
                        {
                            "field": "research_coverage_rate",
                            "label": "Research coverage",
                            "format": "percent",
                        },
                        {
                            "field": "research_coverage_numerator",
                            "label": "Covered",
                            "format": "number",
                        },
                        {
                            "field": "research_coverage_denominator",
                            "label": "Eligible",
                            "format": "number",
                        },
                        {
                            "field": "research_coverage_threshold_status",
                            "label": "Coverage status",
                        },
                        {
                            "field": "fresh_source_rate",
                            "label": "Fresh sources",
                            "format": "percent",
                        },
                        {
                            "field": "fresh_source_numerator",
                            "label": "Fresh",
                            "format": "number",
                        },
                        {
                            "field": "fresh_source_denominator",
                            "label": "Verified",
                            "format": "number",
                        },
                        {
                            "field": "fresh_source_threshold_status",
                            "label": "Freshness status",
                        },
                    ],
                },
                {
                    "id": "slot_table",
                    "title": "Exact slot ledger",
                    "dataset": "slots",
                    "sourceId": "slots_source",
                    "defaultSort": {"field": "expected_at", "direction": "asc"},
                    "columns": [
                        {"field": "session", "label": "Session", "type": "date"},
                        {"field": "lane", "label": "Lane"},
                        {"field": "expected_at", "label": "Expected at"},
                        {"field": "slot_state", "label": "Slot state"},
                        {"field": "journal_status", "label": "Journal"},
                        {"field": "publication_contract", "label": "Report contract"},
                        {"field": "expectation", "label": "Expected action"},
                        {"field": "diff_reason", "label": "Diff reason"},
                        {
                            "field": "eligible_count",
                            "label": "Eligible",
                            "format": "number",
                        },
                        {
                            "field": "published_item_count",
                            "label": "Published",
                            "format": "number",
                        },
                        {
                            "field": "research_attempted_count",
                            "label": "Research attempted",
                            "format": "number",
                        },
                        {
                            "field": "research_succeeded_count",
                            "label": "Research succeeded",
                        },
                        {
                            "field": "research_timed_out_count",
                            "label": "Research timed out",
                        },
                        {
                            "field": "verified_evidence_count",
                            "label": "Verified evidence",
                            "format": "number",
                        },
                        {"field": "run_id", "label": "Run ID"},
                    ],
                },
                {
                    "id": "case_table",
                    "title": "Observed case outcomes",
                    "dataset": "cases",
                    "sourceId": "cases_source",
                    "defaultSort": {"field": "ticker", "direction": "asc"},
                    "columns": [
                        {"field": "session", "label": "Session", "type": "date"},
                        {"field": "lane", "label": "Lane"},
                        {"field": "ticker", "label": "Ticker"},
                        {"field": "actual_action", "label": "Actual"},
                        {"field": "expectation", "label": "Expectation"},
                        {"field": "diff_reason", "label": "Diff reason"},
                        {
                            "field": "verified_evidence_count",
                            "label": "Evidence",
                            "format": "number",
                        },
                        {"field": "run_id", "label": "Run ID"},
                    ],
                },
                {
                    "id": "hard_metrics_table",
                    "title": "Hard graduation metrics",
                    "dataset": "hard_metrics",
                    "sourceId": "hard_metrics_source",
                    "defaultSort": {"field": "metric", "direction": "asc"},
                    "columns": [
                        {"field": "metric", "label": "Metric"},
                        {"field": "value", "label": "Observed"},
                    ],
                },
            ],
            "sources": sources,
            "blocks": [
                {
                    "id": "headline_metrics",
                    "type": "metric-strip",
                    "cardIds": [
                        "terminal_slots",
                        "completed_sessions",
                        "due_coverage",
                        "provider_failure",
                        "research_coverage",
                        "fresh_sources",
                        "unexplained_diffs",
                    ],
                },
                {
                    "id": "quality_block",
                    "type": "table",
                    "tableId": "quality_table",
                },
                {
                    "id": "hard_metrics_block",
                    "type": "table",
                    "tableId": "hard_metrics_table",
                },
                {
                    "id": "provider_block",
                    "type": "table",
                    "tableId": "provider_table",
                },
                {
                    "id": "lane_quality_block",
                    "type": "table",
                    "tableId": "lane_quality_table",
                },
                {
                    "id": "manual_caveat",
                    "type": "markdown",
                    "body": (
                        "Manual graduation checks remain required for privacy, "
                        "advice-only capability access, deterministic replay, holding "
                        "universe coverage, hard-SELL preservation, and existing-pipeline "
                        "impact. This dashboard never grants cutover approval."
                    ),
                },
                {
                    "id": "slots_block",
                    "type": "table",
                    "tableId": "slot_table",
                },
                {
                    "id": "cases_block",
                    "type": "table",
                    "tableId": "case_table",
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": {
                "summary": summary,
                "quality": quality_rows,
                "provider_metrics": dashboard_provider_metrics,
                "lane_quality": dashboard_lane_quality,
                "hard_metrics": hard_metric_rows,
                "slots": dashboard_slots,
                "cases": dashboard_cases,
            },
        },
        "sources": sources,
    }
    return artifact


__all__ = ["build_shadow_dashboard_artifact_v0"]
