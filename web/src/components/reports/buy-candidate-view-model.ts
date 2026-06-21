import { readNumberLike, readString } from "./helpers";
import { RISK_GUIDE_NOTICE } from "./risk-guidance";
import type { ReportJson } from "./types";

const MAX_REASON_CHIPS = 5;

const SCORE_TOKEN_TO_CHIP: Record<string, { label: string; tone: ChipTone }> = {
  ema_cross: { label: "EMA 크로스", tone: "positive" },
  rsi: { label: "RSI 반등", tone: "positive" },
  gap: { label: "갭 OK", tone: "positive" },
  liquidity: { label: "유동성 OK", tone: "positive" },
  sma200: { label: "SMA200 상단", tone: "positive" },
  slope: { label: "기울기↑", tone: "positive" },
  rs: { label: "RS OK", tone: "positive" },
  rs_below: { label: "RS 약함", tone: "warning" },
};

const SCORE_TOKEN_PRIORITY = [
  "ema_cross",
  "rsi",
  "gap",
  "liquidity",
  "sma200",
  "slope",
  "rs",
  "rs_below",
];

const PATTERN_LABEL: Record<string, string> = {
  trend_pullback_bounce: "눌림 반등",
  swing_high_breakout: "돌파",
  rsi_oversold_reversal: "RSI 반전",
};

const ENTRY_STATE_LABEL: Record<string, { label: string; tone: ChipTone }> = {
  READY: { label: "READY(확인)", tone: "positive" },
  WATCH: { label: "WATCH(대기)", tone: "neutral" },
};

const ENTRY_STATE_REASON_LABEL: Record<string, string> = {
  "Early setup; awaiting confirmation": "초기 셋업: 확인 신호 대기",
  "Pullback bounce confirmed on close": "눌림 반등: 종가 확인",
  "Pullback bounce forming; wait for EMA reclaim/RSI>50 or volume thrust":
    "눌림 반등 형성: EMA/RSI/거래량 확인 대기",
  "Breakout extended (>1 ATR above swing high); consider waiting":
    "돌파 과열(전고점 대비 1ATR↑): 추격 주의",
  "KR breakout needs one more close confirmation above swing high":
    "KR 돌파: 종가 확인 1회 추가 필요",
  "Breakout close above swing high with volume":
    "돌파: 전고점 상단 종가+거래량",
  "RSI rebound and close above EMA short": "RSI 반등+EMA 상단 종가",
  "Early reversal; need RSI>=45 and close above EMA short":
    "초기 반전: RSI>=45 및 EMA 상단 종가 필요",
};

export type ChipTone = "positive" | "warning" | "neutral";

export interface ReasonChip {
  label: string;
  tone: ChipTone;
}

export interface DetailSection {
  title: string;
  lines: string[];
}

export interface BuyCandidateViewModel {
  reasonChips: ReasonChip[];
  reasonSummary: string;
  riskSummary: string;
  detailSections: DetailSection[];
}

interface StructuredReason {
  id: string;
  label: string;
  kind: string | null;
  status: string | null;
  value?: unknown;
  threshold?: unknown;
}

function readNonDashString(value: unknown): string | null {
  const parsed = readString(value);
  if (!parsed || parsed === "-") {
    return null;
  }
  return parsed;
}

function inferHybrid(row: ReportJson, strategyMode: string | null): boolean {
  return (
    readString(row.pattern) !== null ||
    readString(row.entry_state) !== null ||
    strategyMode === "sma_ema_hybrid"
  );
}

function parseStructuredReasons(row: ReportJson): StructuredReason[] {
  if (!Array.isArray(row.reasons)) {
    return [];
  }
  return row.reasons.flatMap((entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      return [];
    }
    const candidate = entry as Record<string, unknown>;
    const id = readString(candidate.id);
    const label = readString(candidate.label);
    if (!id || !label) {
      return [];
    }
    return [
      {
        id,
        label,
        kind: readString(candidate.kind),
        status: readString(candidate.status),
        value: candidate.value,
        threshold: candidate.threshold,
      },
    ];
  });
}

function parseCsvTokens(raw: string | null): string[] {
  if (!raw) {
    return [];
  }
  return raw
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
}

function translatedPatternReasons(row: ReportJson): string[] {
  return parseCsvTokens(readString(row.pattern_reasons)).map(
    translatePatternReason,
  );
}

function truncateLabel(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, Math.max(1, maxLength - 1))}…`;
}

function translatePatternReason(reason: string): string {
  if (reason === "Close reclaimed EMA short") {
    return "EMA 회복";
  }
  if (reason === "Bullish candle with rising volume") {
    return "양봉+거래량";
  }
  if (reason === "RSI crossed above 50") {
    return "RSI 50 상향";
  }
  if (reason === "Reversal candle near EMA short") {
    return "EMA 부근 반전";
  }
  if (reason === "Reversal off EMA short/mid with volume") {
    return "EMA 지지 반전(거래량)";
  }
  const breakoutMatch = reason.match(
    /^Close broke above recent swing high with volume > (\d+)d avg \(excluding breakout bar\)$/,
  );
  if (breakoutMatch) {
    return `전고점 돌파(거래량>${breakoutMatch[1]}일평균)`;
  }
  return truncateLabel(reason, 18);
}

function translateEntryStateReason(reason: string | null): string | null {
  if (!reason) {
    return null;
  }
  return ENTRY_STATE_REASON_LABEL[reason] ?? reason;
}

function formatGapGuardPct(row: ReportJson): string | null {
  const pctString = readNonDashString(row.gap_guard_pct);
  if (pctString) {
    return pctString;
  }
  const pctValue = readNumberLike(row.gap_guard_pct_value);
  if (pctValue !== null) {
    return `±${(pctValue * 100).toFixed(1)}%`;
  }
  return null;
}

function limitReasonChips(chips: ReasonChip[]): ReasonChip[] {
  if (chips.length <= MAX_REASON_CHIPS) {
    return chips;
  }
  const visible = chips.slice(0, MAX_REASON_CHIPS - 1);
  visible.push({
    label: `+${chips.length - visible.length}`,
    tone: "neutral",
  });
  return visible;
}

function structuredReasonTone(reason: StructuredReason): ChipTone {
  const status = (reason.status ?? "").toLowerCase();
  if (status === "warn" || status === "warning") {
    return "warning";
  }
  if (status === "neutral") {
    return "neutral";
  }
  return "positive";
}

function buildStructuredReasonChips(reasons: StructuredReason[]): ReasonChip[] {
  const chips = reasons
    .filter((reason) => reason.id !== "entry_state_reason")
    .map((reason) => ({
      label: reason.label,
      tone: structuredReasonTone(reason),
    }));
  return limitReasonChips(chips);
}

function buildStructuredReasonSummary(reasons: StructuredReason[]): string {
  const primary = reasons.filter((reason) => reason.kind !== "risk");
  const source = primary.length > 0 ? primary : reasons;
  if (source.length === 0) {
    return "-";
  }
  return source
    .slice(0, 3)
    .map((reason) => reason.label)
    .join(" · ");
}

function buildEmaChips(row: ReportJson): ReasonChip[] {
  const tokens = new Set(parseCsvTokens(readString(row.score_notes)));
  const chips = SCORE_TOKEN_PRIORITY.flatMap((token) => {
    if (!tokens.has(token)) {
      return [];
    }
    return [SCORE_TOKEN_TO_CHIP[token]];
  });
  return limitReasonChips(chips);
}

function buildHybridChips(row: ReportJson): ReasonChip[] {
  const chips: ReasonChip[] = [];
  const pattern = readString(row.pattern);
  if (pattern) {
    chips.push({
      label: PATTERN_LABEL[pattern] ?? pattern,
      tone: "positive",
    });
  }
  const entryState = readString(row.entry_state);
  if (entryState && ENTRY_STATE_LABEL[entryState]) {
    chips.push(ENTRY_STATE_LABEL[entryState]);
  }
  const translatedReasons = translatedPatternReasons(row);
  for (const reason of translatedReasons.slice(0, 2)) {
    chips.push({ label: reason, tone: "neutral" });
  }
  const gapGuardPct = formatGapGuardPct(row);
  if (gapGuardPct) {
    chips.push({ label: `gap guard ${gapGuardPct}`, tone: "neutral" });
  }
  return limitReasonChips(chips);
}

function buildEmaSummary(row: ReportJson): string {
  const fragments: string[] = ["EMA20/50 크로스 + RSI 반등"];
  const gap = readNonDashString(row.gap);
  const gapThreshold = readNonDashString(row.gap_threshold);
  if (gap && gapThreshold) {
    fragments.push(`갭 ${gap} / 한도 ${gapThreshold}`);
  } else if (gap) {
    fragments.push(`갭 ${gap}`);
  }
  const avgDollarVolume = readNonDashString(row.avg_dollar_volume);
  if (avgDollarVolume) {
    fragments.push(`유동성 ${avgDollarVolume}`);
  }
  const rsDiff = readNonDashString(row.rs_diff);
  if (rsDiff) {
    fragments.push(`RS ${rsDiff}`);
  }
  return fragments.join(" · ");
}

function buildHybridSummary(row: ReportJson): string {
  const pattern = readString(row.pattern);
  const patternLabel = pattern
    ? (PATTERN_LABEL[pattern] ?? pattern)
    : "패턴 후보";
  const entryState = readString(row.entry_state);
  const entryStateLabel =
    (entryState && ENTRY_STATE_LABEL[entryState]?.label) ?? "상태 미정";
  const translated = translatedPatternReasons(row);
  if (translated.length > 0) {
    return `${patternLabel} / ${entryStateLabel} · ${translated
      .slice(0, 2)
      .join(" · ")}`;
  }
  return `${patternLabel} / ${entryStateLabel}`;
}

function buildRiskSummary(
  row: ReportJson,
  structuredReasons: StructuredReason[],
): string {
  const riskGuide = readNonDashString(row.risk_guide);
  const gapGuardPct = formatGapGuardPct(row);
  const riskGuideParts: string[] = [];
  if (riskGuide) {
    riskGuideParts.push(`의사결정 가이드: ${riskGuide}`);
  }
  if (gapGuardPct) {
    riskGuideParts.push(`gap guard ${gapGuardPct}`);
  }
  if (riskGuideParts.length > 0) {
    riskGuideParts.push(RISK_GUIDE_NOTICE);
    return riskGuideParts.join(" · ");
  }
  const riskLabels = structuredReasons
    .filter((reason) => reason.kind === "risk")
    .map((reason) => reason.label);
  if (riskLabels.length > 0) {
    return riskLabels.join(" · ");
  }
  return "-";
}

function buildReasonDetailLines(
  row: ReportJson,
  isHybrid: boolean,
  reasonSummary: string,
  structuredReasons: StructuredReason[],
): string[] {
  if (structuredReasons.length > 0) {
    const lines = structuredReasons.map((reason) => reason.label);
    if (isHybrid) {
      const entryStateReason = translateEntryStateReason(
        readString(row.entry_state_reason),
      );
      if (entryStateReason) {
        return [entryStateReason, ...lines];
      }
    }
    return lines;
  }
  if (!isHybrid) {
    const lines: string[] = [reasonSummary];
    const scoreNotes = readNonDashString(row.score_notes);
    if (scoreNotes) {
      lines.push(`score_notes: ${scoreNotes}`);
    }
    return lines;
  }
  const lines: string[] = [];
  const entryStateReason = translateEntryStateReason(
    readString(row.entry_state_reason),
  );
  if (entryStateReason) {
    lines.push(entryStateReason);
  }
  lines.push(...translatedPatternReasons(row));
  if (lines.length === 0) {
    lines.push(reasonSummary);
  }
  return lines;
}

function pushMetricLine(lines: string[], label: string, value: unknown): void {
  const parsed = readNonDashString(value);
  if (!parsed) {
    return;
  }
  lines.push(`${label}: ${parsed}`);
}

function buildMetricLines(row: ReportJson, isHybrid: boolean): string[] {
  const lines: string[] = [];
  if (!isHybrid) {
    pushMetricLine(lines, "EMA20", row.ema20);
    pushMetricLine(lines, "EMA50", row.ema50);
    pushMetricLine(lines, "RSI14", row.rsi14);
    pushMetricLine(lines, "ATR14", row.atr14);
    pushMetricLine(lines, "갭", row.gap);
    pushMetricLine(lines, "갭 임계", row.gap_threshold);
    pushMetricLine(lines, "평균 거래대금", row.avg_dollar_volume);
    pushMetricLine(lines, "RS diff", row.rs_diff);
    pushMetricLine(lines, "SMA200", row.sma200);
    return lines;
  }

  pushMetricLine(lines, "SMA trend", row.sma_trend);
  pushMetricLine(lines, "EMA short", row.ema_short);
  pushMetricLine(lines, "EMA mid", row.ema_mid);
  pushMetricLine(lines, "RSI", row.rsi);
  pushMetricLine(lines, "ATR14", row.atr14);
  pushMetricLine(lines, "gap guard", row.gap_guard_pct);
  const dynamicIndicatorEntries = Object.entries(row)
    .filter(
      ([key, value]) =>
        /^(sma|ema|rsi)\d+$/i.test(key) && readNonDashString(value),
    )
    .sort(([left], [right]) => left.localeCompare(right));
  for (const [key, value] of dynamicIndicatorEntries) {
    pushMetricLine(lines, key.toUpperCase(), value);
  }
  return lines;
}

function buildRiskDetailLines(row: ReportJson, riskSummary: string): string[] {
  const lines: string[] = [riskSummary];
  const gapGuardUp = readNonDashString(row.gap_guard_up_price);
  if (gapGuardUp) {
    lines.push(`상단 가이드: ${gapGuardUp}`);
  }
  const gapGuardDown = readNonDashString(row.gap_guard_down_price);
  if (gapGuardDown) {
    lines.push(`하단 가이드: ${gapGuardDown}`);
  }
  return lines;
}

function buildContextLines(row: ReportJson): string[] {
  const lines: string[] = [];
  pushMetricLine(lines, "평가일", row.eval_date);
  pushMetricLine(lines, "통화", row.currency);
  pushMetricLine(lines, "시장 상태", row.market_status);
  pushMetricLine(lines, "데이터 소스", row.data_source);
  pushMetricLine(lines, "프로바이더", row.provider);
  return lines;
}

export function buildBuyCandidateViewModel(
  row: ReportJson,
  strategyMode: string | null,
): BuyCandidateViewModel {
  const structuredReasons = parseStructuredReasons(row);
  const isHybrid = inferHybrid(row, strategyMode);
  const reasonChips =
    structuredReasons.length > 0
      ? buildStructuredReasonChips(structuredReasons)
      : isHybrid
        ? buildHybridChips(row)
        : buildEmaChips(row);
  const reasonSummary =
    structuredReasons.length > 0
      ? buildStructuredReasonSummary(structuredReasons)
      : isHybrid
        ? buildHybridSummary(row)
        : buildEmaSummary(row);
  const riskSummary = buildRiskSummary(row, structuredReasons);
  const detailSections: DetailSection[] = [
    {
      title: "근거 상세",
      lines: buildReasonDetailLines(
        row,
        isHybrid,
        reasonSummary,
        structuredReasons,
      ),
    },
    {
      title: "지표 스냅샷",
      lines: buildMetricLines(row, isHybrid),
    },
    {
      title: "리스크 상세",
      lines: buildRiskDetailLines(row, riskSummary),
    },
    {
      title: "컨텍스트",
      lines: buildContextLines(row),
    },
  ];

  for (const section of detailSections) {
    if (section.lines.length === 0) {
      section.lines.push("-");
    }
  }

  return {
    reasonChips,
    reasonSummary,
    riskSummary,
    detailSections,
  };
}
