import { z } from "zod";

const timestampA1Schema = z
  .string()
  .regex(/Z$/u)
  .pipe(z.iso.datetime({ offset: false }));
const sourceIdentifierA1Schema = z
  .object({
    scheme: z.string().regex(/^[A-Z][A-Z0-9_]{0,31}$/u),
    value: z.string().min(1).max(128),
  })
  .strict();
const issuerA1Schema = z
  .object({
    issuer_id: z.uuid(),
    legal_name: z.string().min(1).max(256),
    source_identifiers: z.array(sourceIdentifierA1Schema).min(1),
  })
  .strict();
const instrumentA1Schema = z
  .object({
    instrument_id: z.uuid(),
    issuer_id: z.uuid(),
    security_type: z.enum(["COMMON_STOCK", "PREFERRED_STOCK", "ETF"]),
    currency: z.string().regex(/^[A-Z]{3}$/u),
  })
  .strict();
const listingAliasA1Schema = z
  .object({
    listing_alias_id: z.uuid(),
    instrument_id: z.uuid(),
    exchange_mic: z.string().regex(/^[A-Z0-9]{4}$/u),
    ticker: z.string().regex(/^[A-Z][A-Z0-9./-]{0,31}$/u),
    valid_from: timestampA1Schema,
    valid_to: timestampA1Schema.nullable(),
    registry_version: z.string().min(1).max(128),
  })
  .strict()
  .refine(
    (alias) =>
      alias.valid_to === null ||
      Date.parse(alias.valid_to) > Date.parse(alias.valid_from),
    { path: ["valid_to"], message: "Must be later than valid_from" },
  );
const evidenceIdentitySealA1Schema = z
  .object({
    evidence_seal_id: z.uuid(),
    source_id: z.uuid(),
    instrument_id: z.uuid(),
    issuer_id: z.uuid(),
    registry_version: z.string().min(1).max(128),
    source_event_time: timestampA1Schema,
    source_issuer_identifier: sourceIdentifierA1Schema,
    scope: z.enum(["ISSUER", "INSTRUMENT"]),
    exchange_mic: z.string().regex(/^[A-Z0-9]{4}$/u),
    ticker: z.string().regex(/^[A-Z][A-Z0-9./-]{0,31}$/u),
    sealed_at: timestampA1Schema,
    actor_kind: z.literal("SOURCE_VALIDATOR"),
  })
  .strict();

const stableIdentityA1Schema = z
  .object({
    registry_version: z.string().min(1).max(128),
    issuers: z.array(issuerA1Schema).min(1),
    instruments: z.array(instrumentA1Schema).min(1),
    listing_aliases: z.array(listingAliasA1Schema).min(1),
    evidence_seals: z.array(evidenceIdentitySealA1Schema).min(1),
  })
  .strict()
  .superRefine((identity, context) => {
    const issuers = new Map(
      identity.issuers.map((issuer) => [issuer.issuer_id, issuer]),
    );
    const instruments = new Map(
      identity.instruments.map((instrument) => [
        instrument.instrument_id,
        instrument,
      ]),
    );
    const evidenceSealIds = new Set(
      identity.evidence_seals.map((seal) => seal.evidence_seal_id),
    );
    const evidenceSourceScopes = new Set(
      identity.evidence_seals.map((seal) =>
        [seal.source_id, seal.instrument_id, seal.registry_version].join(
          "\u0000",
        ),
      ),
    );
    if (issuers.size !== identity.issuers.length) {
      context.addIssue({
        code: "custom",
        path: ["issuers"],
        message: "issuer_id values must be unique",
      });
    }
    if (instruments.size !== identity.instruments.length) {
      context.addIssue({
        code: "custom",
        path: ["instruments"],
        message: "instrument_id values must be unique",
      });
    }
    if (evidenceSealIds.size !== identity.evidence_seals.length) {
      context.addIssue({
        code: "custom",
        path: ["evidence_seals"],
        message: "evidence_seal_id values must be unique",
      });
    }
    if (evidenceSourceScopes.size !== identity.evidence_seals.length) {
      context.addIssue({
        code: "custom",
        path: ["evidence_seals"],
        message:
          "source_id, instrument_id, and registry_version must be unique",
      });
    }
    identity.evidence_seals.forEach((seal, index) => {
      const rebound = identity.evidence_seals
        .slice(0, index)
        .some(
          (prior) =>
            prior.source_id === seal.source_id &&
            prior.instrument_id !== seal.instrument_id &&
            (prior.issuer_id !== seal.issuer_id ||
              prior.scope === "INSTRUMENT" ||
              seal.scope === "INSTRUMENT"),
        );
      if (rebound) {
        context.addIssue({
          code: "custom",
          path: ["evidence_seals"],
          message: "source scope cannot be rebound to another instrument",
        });
      }
    });
    identity.instruments.forEach((instrument, index) => {
      if (!issuers.has(instrument.issuer_id)) {
        context.addIssue({
          code: "custom",
          path: ["instruments", index, "issuer_id"],
          message: "Must reference a stable issuer_id",
        });
      }
    });
    identity.listing_aliases.forEach((alias, index) => {
      if (!instruments.has(alias.instrument_id)) {
        context.addIssue({
          code: "custom",
          path: ["listing_aliases", index, "instrument_id"],
          message: "Must reference a stable instrument_id",
        });
      }
      if (alias.registry_version !== identity.registry_version) {
        context.addIssue({
          code: "custom",
          path: ["listing_aliases", index, "registry_version"],
          message: "Must match the sealed registry version",
        });
      }
    });
    identity.evidence_seals.forEach((seal, index) => {
      const path = ["evidence_seals", index] as const;
      const instrument = instruments.get(seal.instrument_id);
      const issuer = issuers.get(seal.issuer_id);
      if (instrument === undefined) {
        context.addIssue({
          code: "custom",
          path: [...path, "instrument_id"],
          message: "Must reference a stable instrument_id",
        });
        return;
      }
      if (instrument.issuer_id !== seal.issuer_id) {
        context.addIssue({
          code: "custom",
          path: [...path, "issuer_id"],
          message: "Must match the instrument issuer_id",
        });
      }
      if (seal.registry_version !== identity.registry_version) {
        context.addIssue({
          code: "custom",
          path: [...path, "registry_version"],
          message: "Must match the sealed registry version",
        });
      }
      if (
        issuer === undefined ||
        !issuer.source_identifiers.some(
          (identifier) =>
            identifier.scheme === seal.source_issuer_identifier.scheme &&
            identifier.value === seal.source_issuer_identifier.value,
        )
      ) {
        context.addIssue({
          code: "custom",
          path: [...path, "source_issuer_identifier"],
          message: "Must be registered for the exact issuer",
        });
      }
      const aliases = identity.listing_aliases.filter(
        (alias) =>
          alias.instrument_id === seal.instrument_id &&
          alias.exchange_mic === seal.exchange_mic &&
          alias.ticker === seal.ticker,
      );
      if (aliases.length !== 1) {
        context.addIssue({
          code: "custom",
          path: [...path],
          message: "Alias lookup must resolve to exactly one stable instrument",
        });
        return;
      }
      const alias = aliases[0];
      const eventTime = Date.parse(seal.source_event_time);
      if (
        eventTime < Date.parse(alias.valid_from) ||
        (alias.valid_to !== null && eventTime >= Date.parse(alias.valid_to))
      ) {
        context.addIssue({
          code: "custom",
          path: [...path, "source_event_time"],
          message: "Must fall inside the exact alias validity window",
        });
      }
    });
  });

const mandateA1Schema = z
  .object({
    mandate_id: z.uuid(),
    instrument_id: z.uuid(),
    broker_position_id: z.uuid().nullable(),
    owner_actor_id: z.uuid(),
    created_at: timestampA1Schema,
  })
  .strict();
const mandateVersionA1Schema = z
  .object({
    mandate_version_id: z.uuid(),
    mandate_id: z.uuid(),
    version_number: z.number().int().positive(),
    supersedes_version_id: z.uuid().nullable(),
    classification_state: z.enum([
      "UNCLASSIFIED",
      "ACTIVE",
      "EXIT_REVIEW",
      "CLOSED",
    ]),
    horizon: z.enum(["SWING", "LONG_TERM"]).nullable(),
    proposed_horizon: z.enum(["SWING", "LONG_TERM"]).nullable(),
    approval_state: z.enum(["DRAFT", "APPROVED", "NEEDS_REAPPROVAL"]),
    thesis: z.string().min(1).max(2000).nullable(),
    invalidation_conditions: z.array(z.string().min(1).max(1000)),
    approved_by_kind: z.literal("USER").nullable(),
    approved_at: timestampA1Schema.nullable(),
    policy_version: z.string().min(1).max(128),
    effective_from: timestampA1Schema.nullable(),
    effective_to: timestampA1Schema.nullable(),
  })
  .strict();
const activationCommandA1Schema = z
  .object({
    command_id: z.uuid(),
    mandate_id: z.uuid(),
    draft_mandate_version_id: z.uuid(),
    expected_mandate_version_id: z.uuid(),
    actor_kind: z.literal("USER"),
    actor_id: z.uuid(),
    broker_snapshot_version: z.number().int().positive(),
    allocation_version: z.number().int().positive(),
    requested_at: timestampA1Schema,
  })
  .strict();
const mandateVersionCoreA1Schema = z
  .object({
    mandates: z.array(mandateA1Schema).min(1),
    versions: z.array(mandateVersionA1Schema).min(1),
    activation_commands: z.array(activationCommandA1Schema).min(1),
  })
  .strict()
  .superRefine((core, context) => {
    const mandates = new Map(
      core.mandates.map((mandate) => [mandate.mandate_id, mandate]),
    );
    const versions = new Map(
      core.versions.map((version) => [version.mandate_version_id, version]),
    );
    if (mandates.size !== core.mandates.length) {
      context.addIssue({
        code: "custom",
        path: ["mandates"],
        message: "mandate_id values must be unique",
      });
    }
    if (versions.size !== core.versions.length) {
      context.addIssue({
        code: "custom",
        path: ["versions"],
        message: "mandate_version_id values must be unique",
      });
    }
    const activeByMandate = new Map<string, (typeof core.versions)[number]>();
    const versionNumbers = new Set<string>();
    core.versions.forEach((version, index) => {
      if (!mandates.has(version.mandate_id)) {
        context.addIssue({
          code: "custom",
          path: ["versions", index, "mandate_id"],
          message: "Must reference a stable mandate_id",
        });
      }
      const key = `${version.mandate_id}:${version.version_number}`;
      if (versionNumbers.has(key)) {
        context.addIssue({
          code: "custom",
          path: ["versions"],
          message: "version_number must be unique within a mandate",
        });
      }
      versionNumbers.add(key);
      const superseded =
        version.supersedes_version_id === null
          ? undefined
          : versions.get(version.supersedes_version_id);
      if (
        version.supersedes_version_id !== null &&
        (superseded === undefined ||
          superseded.mandate_id !== version.mandate_id ||
          superseded.version_number >= version.version_number)
      ) {
        context.addIssue({
          code: "custom",
          path: ["versions", index, "supersedes_version_id"],
          message: "Must reference an earlier version on the exact mandate",
        });
      }
      const activeApproved =
        version.classification_state === "ACTIVE" &&
        version.approval_state === "APPROVED" &&
        version.effective_to === null;
      if (activeApproved) {
        if (activeByMandate.has(version.mandate_id)) {
          context.addIssue({
            code: "custom",
            path: ["versions"],
            message: "A mandate can have at most one ACTIVE/APPROVED version",
          });
        }
        activeByMandate.set(version.mandate_id, version);
        if (
          version.horizon === null ||
          version.proposed_horizon !== null ||
          version.thesis === null ||
          version.invalidation_conditions.length === 0 ||
          version.approved_by_kind !== "USER" ||
          version.approved_at === null ||
          version.effective_from === null
        ) {
          context.addIssue({
            code: "custom",
            path: ["versions", index],
            message:
              "ACTIVE/APPROVED requires a complete user-approved version",
          });
        }
      } else if (
        version.classification_state === "UNCLASSIFIED" &&
        ["DRAFT", "NEEDS_REAPPROVAL"].includes(version.approval_state)
      ) {
        if (
          version.horizon !== null ||
          version.approved_by_kind !== null ||
          version.approved_at !== null ||
          version.effective_from !== null
        ) {
          context.addIssue({
            code: "custom",
            path: ["versions", index],
            message: "An unapproved version cannot be active or approved",
          });
        }
      } else if (
        ["EXIT_REVIEW", "CLOSED"].includes(version.classification_state) &&
        version.approval_state === "APPROVED" &&
        version.horizon === null &&
        version.approved_by_kind === "USER"
      ) {
        // This is a terminal user-approved version.
      } else {
        context.addIssue({
          code: "custom",
          path: ["versions", index],
          message:
            "Classification, horizon, and approval combination is invalid",
        });
      }
    });
    const commandIds = new Set<string>();
    core.activation_commands.forEach((command, index) => {
      if (commandIds.has(command.command_id)) {
        context.addIssue({
          code: "custom",
          path: ["activation_commands"],
          message: "activation command_id values must be unique",
        });
      }
      commandIds.add(command.command_id);
      const mandate = mandates.get(command.mandate_id);
      const draft = versions.get(command.draft_mandate_version_id);
      const active = activeByMandate.get(command.mandate_id);
      if (
        mandate === undefined ||
        draft === undefined ||
        draft.mandate_id !== command.mandate_id ||
        draft.classification_state !== "UNCLASSIFIED" ||
        !["DRAFT", "NEEDS_REAPPROVAL"].includes(draft.approval_state) ||
        draft.proposed_horizon === null ||
        draft.thesis === null ||
        draft.invalidation_conditions.length === 0
      ) {
        context.addIssue({
          code: "custom",
          path: ["activation_commands", index, "draft_mandate_version_id"],
          message: "Draft must be complete and belong to the exact mandate",
        });
      }
      if (
        mandate !== undefined &&
        command.actor_id !== mandate.owner_actor_id
      ) {
        context.addIssue({
          code: "custom",
          path: ["activation_commands", index, "actor_id"],
          message: "Must match the mandate owner",
        });
      }
      if (
        active === undefined ||
        active.mandate_version_id !== command.expected_mandate_version_id
      ) {
        context.addIssue({
          code: "custom",
          path: ["activation_commands", index, "expected_mandate_version_id"],
          message: "Must match the exact current active version",
        });
      }
      if (
        draft !== undefined &&
        draft.supersedes_version_id !== command.expected_mandate_version_id
      ) {
        context.addIssue({
          code: "custom",
          path: ["activation_commands", index, "draft_mandate_version_id"],
          message: "Draft must supersede the exact expected mandate version",
        });
      }
    });
  });

const decimalQuantityA1Schema = z
  .string()
  .regex(/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/u);
const decimalMetricA1Schema = z
  .string()
  .regex(/^-?(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/u);
const decimalQuantityToMicros = (value: string): bigint => {
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
};
const decimalMetricToMicros = (value: string): bigint => {
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction = ""] = unsigned.split(".");
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
  return negative ? -micros : micros;
};
const hashA1Schema = z.string().regex(/^sha256:[0-9a-f]{64}$/u);
const brokerPositionA1Schema = z
  .object({
    broker_position_id: z.uuid(),
    instrument_id: z.uuid(),
    account_ref_hash: hashA1Schema,
    currency: z.string().regex(/^[A-Z]{3}$/u),
  })
  .strict();
const brokerPositionSnapshotA1Schema = z
  .object({
    broker_position_snapshot_id: z.uuid(),
    broker_position_id: z.uuid(),
    snapshot_version: z.number().int().positive(),
    quantity: decimalQuantityA1Schema,
    currency: z.string().regex(/^[A-Z]{3}$/u),
    watermark: z.string().min(1).max(128),
    sealed_input_hash: hashA1Schema,
  })
  .strict();
const allocationA1Schema = z
  .object({
    allocation_id: z.uuid(),
    broker_position_id: z.uuid(),
    allocation_version: z.number().int().positive(),
    snapshot_version: z.number().int().positive(),
    active: z.boolean(),
    decision_eligible: z.boolean(),
  })
  .strict();
const positionSliceA1Schema = z
  .object({
    slice_id: z.uuid(),
    allocation_id: z.uuid(),
    mandate_version_id: z.uuid().nullable(),
    quantity: decimalQuantityA1Schema,
    currency: z.string().regex(/^[A-Z]{3}$/u),
    classification_state: z.enum([
      "ACTIVE",
      "UNCLASSIFIED",
      "PENDING_ALLOCATION",
    ]),
    decision_eligible: z.boolean(),
  })
  .strict();
const rebaseCommandA1Schema = z
  .object({
    command_id: z.uuid(),
    rebase_evidence_id: z.uuid(),
    broker_position_id: z.uuid(),
    source_snapshot_version: z.number().int().positive(),
    target_snapshot_version: z.number().int().positive(),
    target_quantity: decimalQuantityA1Schema,
    currency: z.string().regex(/^[A-Z]{3}$/u),
    cause: z.enum([
      "ZERO_DELTA",
      "UNIQUE_BUY",
      "UNRESOLVED_BUY",
      "UNIQUE_SELL",
      "AMBIGUOUS_SELL",
      "POSITION_CLOSED",
      "VERIFIED_CORPORATE_ACTION",
      "AMBIGUOUS_CORPORATE_ACTION",
    ]),
    matched_slice_id: z.uuid().nullable(),
    corporate_action_ratio: z
      .string()
      .regex(/^[1-9][0-9]*(\.[0-9]{1,8})?$/u)
      .nullable(),
    expected_allocation_version: z.number().int().positive(),
    actor_kind: z.literal("DETERMINISTIC"),
    requested_at: timestampA1Schema,
  })
  .strict();
const rebaseEvidenceA1Schema = z
  .object({
    rebase_evidence_id: z.uuid(),
    broker_position_id: z.uuid(),
    source_snapshot_version: z.number().int().positive(),
    target_snapshot_version: z.number().int().positive(),
    cause: z.enum([
      "ZERO_DELTA",
      "UNIQUE_BUY",
      "UNRESOLVED_BUY",
      "UNIQUE_SELL",
      "AMBIGUOUS_SELL",
      "POSITION_CLOSED",
      "VERIFIED_CORPORATE_ACTION",
      "AMBIGUOUS_CORPORATE_ACTION",
    ]),
    matched_slice_id: z.uuid().nullable(),
    corporate_action_ratio: z
      .string()
      .regex(/^[1-9][0-9]*(\.[0-9]{1,8})?$/u)
      .nullable(),
    source_id: z.uuid(),
    evidence_hash: hashA1Schema,
    verification_state: z.enum(["VERIFIED", "UNRESOLVED"]),
    producer_kind: z.literal("DETERMINISTIC"),
  })
  .strict();
const positionSliceCoreA1Schema = z
  .object({
    broker_positions: z.array(brokerPositionA1Schema).min(1),
    snapshots: z.array(brokerPositionSnapshotA1Schema).min(2),
    allocations: z.array(allocationA1Schema).min(1),
    rebase_evidence: z.array(rebaseEvidenceA1Schema).min(1),
    slices: z.array(positionSliceA1Schema).min(1),
    rebase_commands: z.array(rebaseCommandA1Schema).min(1),
  })
  .strict()
  .superRefine((core, context) => {
    const positions = new Map(
      core.broker_positions.map((position) => [
        position.broker_position_id,
        position,
      ]),
    );
    const snapshots = new Map(
      core.snapshots.map((snapshot) => [
        `${snapshot.broker_position_id}:${snapshot.snapshot_version}`,
        snapshot,
      ]),
    );
    const allocations = new Map(
      core.allocations.map((allocation) => [
        allocation.allocation_id,
        allocation,
      ]),
    );
    const activeByPosition = new Map<
      string,
      (typeof core.allocations)[number]
    >();
    const evidenceById = new Map(
      core.rebase_evidence.map((evidence) => [
        evidence.rebase_evidence_id,
        evidence,
      ]),
    );
    if (evidenceById.size !== core.rebase_evidence.length) {
      context.addIssue({
        code: "custom",
        path: ["rebase_evidence"],
        message: "Rebase evidence identities must be unique",
      });
    }
    if (positions.size !== core.broker_positions.length) {
      context.addIssue({
        code: "custom",
        path: ["broker_positions"],
        message: "broker_position_id values must be unique",
      });
    }
    if (snapshots.size !== core.snapshots.length) {
      context.addIssue({
        code: "custom",
        path: ["snapshots"],
        message: "Snapshot versions must be unique within a broker position",
      });
    }
    core.snapshots.forEach((snapshot, index) => {
      const position = positions.get(snapshot.broker_position_id);
      if (position === undefined || position.currency !== snapshot.currency) {
        context.addIssue({
          code: "custom",
          path: ["snapshots", index, "broker_position_id"],
          message: "Must reference the exact broker position and currency",
        });
      }
    });
    if (allocations.size !== core.allocations.length) {
      context.addIssue({
        code: "custom",
        path: ["allocations"],
        message: "allocation_id values must be unique",
      });
    }
    core.allocations.forEach((allocation, index) => {
      if (allocation.active) {
        if (activeByPosition.has(allocation.broker_position_id)) {
          context.addIssue({
            code: "custom",
            path: ["allocations"],
            message: "A broker position can have at most one active allocation",
          });
        }
        activeByPosition.set(allocation.broker_position_id, allocation);
      }
      if (
        !positions.has(allocation.broker_position_id) ||
        !snapshots.has(
          `${allocation.broker_position_id}:${allocation.snapshot_version}`,
        )
      ) {
        context.addIssue({
          code: "custom",
          path: ["allocations", index],
          message: "Must reference an exact broker snapshot",
        });
      }
    });
    const slicesByAllocation = new Map<string, typeof core.slices>();
    const sliceIds = new Set<string>();
    core.slices.forEach((positionSlice, index) => {
      if (sliceIds.has(positionSlice.slice_id)) {
        context.addIssue({
          code: "custom",
          path: ["slices"],
          message: "slice_id values must be unique",
        });
      }
      sliceIds.add(positionSlice.slice_id);
      const activeStateValid =
        positionSlice.classification_state === "ACTIVE" &&
        positionSlice.mandate_version_id !== null &&
        positionSlice.decision_eligible;
      const quarantineStateValid =
        ["UNCLASSIFIED", "PENDING_ALLOCATION"].includes(
          positionSlice.classification_state,
        ) &&
        positionSlice.mandate_version_id === null &&
        !positionSlice.decision_eligible;
      if (!activeStateValid && !quarantineStateValid) {
        context.addIssue({
          code: "custom",
          path: ["slices", index],
          message:
            "Slice classification, mandate binding, and eligibility are invalid",
        });
      }
      const allocation = allocations.get(positionSlice.allocation_id);
      if (allocation === undefined) {
        context.addIssue({
          code: "custom",
          path: ["slices", index, "allocation_id"],
          message: "Must reference an allocation",
        });
        return;
      }
      const values = slicesByAllocation.get(positionSlice.allocation_id) ?? [];
      values.push(positionSlice);
      slicesByAllocation.set(positionSlice.allocation_id, values);
      const position = positions.get(allocation.broker_position_id);
      if (position?.currency !== positionSlice.currency) {
        context.addIssue({
          code: "custom",
          path: ["slices", index, "currency"],
          message: "Must match the broker position currency",
        });
      }
    });
    core.allocations.forEach((allocation, index) => {
      const snapshot = snapshots.get(
        `${allocation.broker_position_id}:${allocation.snapshot_version}`,
      );
      const total = (
        slicesByAllocation.get(allocation.allocation_id) ?? []
      ).reduce(
        (sum, positionSlice) =>
          sum + decimalQuantityToMicros(positionSlice.quantity),
        0n,
      );
      if (
        snapshot !== undefined &&
        total !== decimalQuantityToMicros(snapshot.quantity)
      ) {
        context.addIssue({
          code: "custom",
          path: ["allocations", index],
          message: "Slice sum must equal the exact broker quantity",
        });
      }
    });
    const commandIds = new Set<string>();
    const identities = new Set<string>();
    core.rebase_commands.forEach((command, index) => {
      const identity = `${command.broker_position_id}:${command.target_snapshot_version}`;
      if (commandIds.has(command.command_id) || identities.has(identity)) {
        context.addIssue({
          code: "custom",
          path: ["rebase_commands"],
          message: "Command and target rebase identities must be unique",
        });
      }
      commandIds.add(command.command_id);
      identities.add(identity);
      const evidence = evidenceById.get(command.rebase_evidence_id);
      const expectedVerificationState = [
        "UNRESOLVED_BUY",
        "AMBIGUOUS_SELL",
        "AMBIGUOUS_CORPORATE_ACTION",
      ].includes(command.cause)
        ? "UNRESOLVED"
        : "VERIFIED";
      if (
        evidence === undefined ||
        evidence.broker_position_id !== command.broker_position_id ||
        evidence.source_snapshot_version !== command.source_snapshot_version ||
        evidence.target_snapshot_version !== command.target_snapshot_version ||
        evidence.cause !== command.cause ||
        evidence.matched_slice_id !== command.matched_slice_id ||
        evidence.corporate_action_ratio !== command.corporate_action_ratio ||
        evidence.verification_state !== expectedVerificationState
      ) {
        context.addIssue({
          code: "custom",
          path: ["rebase_commands", index, "rebase_evidence_id"],
          message: "Must reference exact deterministic rebase evidence",
        });
      }
      const active = activeByPosition.get(command.broker_position_id);
      if (
        active === undefined ||
        active.allocation_version !== command.expected_allocation_version
      ) {
        context.addIssue({
          code: "custom",
          path: ["rebase_commands", index, "expected_allocation_version"],
          message: "Must match the exact active allocation version",
        });
      }
      if (
        active !== undefined &&
        active.snapshot_version !== command.source_snapshot_version
      ) {
        context.addIssue({
          code: "custom",
          path: ["rebase_commands", index, "source_snapshot_version"],
          message: "Must match the active allocation snapshot",
        });
      }
      const target = snapshots.get(identity);
      if (
        target === undefined ||
        target.quantity !== command.target_quantity ||
        target.currency !== command.currency ||
        command.target_snapshot_version <= command.source_snapshot_version
      ) {
        context.addIssue({
          code: "custom",
          path: ["rebase_commands", index, "target_snapshot_version"],
          message: "Must reference the exact newer target snapshot",
        });
      }
      if (active !== undefined) {
        const source = snapshots.get(
          `${command.broker_position_id}:${command.source_snapshot_version}`,
        );
        const sourceSliceIds = new Set(
          (slicesByAllocation.get(active.allocation_id) ?? []).map(
            (positionSlice) => positionSlice.slice_id,
          ),
        );
        if (source !== undefined) {
          const delta =
            decimalQuantityToMicros(command.target_quantity) -
            decimalQuantityToMicros(source.quantity);
          const matched = command.matched_slice_id;
          const ratio = command.corporate_action_ratio;
          const causeValid =
            (command.cause === "ZERO_DELTA" &&
              delta === 0n &&
              matched === null &&
              ratio === null) ||
            (command.cause === "UNIQUE_BUY" &&
              delta > 0n &&
              matched !== null &&
              sourceSliceIds.has(matched) &&
              ratio === null) ||
            (command.cause === "UNRESOLVED_BUY" &&
              delta > 0n &&
              matched === null &&
              ratio === null) ||
            (command.cause === "UNIQUE_SELL" &&
              delta < 0n &&
              matched !== null &&
              sourceSliceIds.has(matched) &&
              ratio === null) ||
            (command.cause === "AMBIGUOUS_SELL" &&
              delta < 0n &&
              matched === null &&
              ratio === null) ||
            (command.cause === "POSITION_CLOSED" &&
              decimalQuantityToMicros(command.target_quantity) === 0n &&
              matched === null &&
              ratio === null) ||
            (command.cause === "VERIFIED_CORPORATE_ACTION" &&
              ratio !== null &&
              matched === null) ||
            (command.cause === "AMBIGUOUS_CORPORATE_ACTION" &&
              matched === null &&
              ratio === null);
          if (!causeValid) {
            context.addIssue({
              code: "custom",
              path: ["rebase_commands", index, "cause"],
              message: "Rebase cause does not match the exact delta evidence",
            });
          }
        }
      }
    });
  });

const predicateAuthorityEventA1Schema = z
  .object({
    predicate_authority_event_id: z.uuid(),
    command_id: z.uuid(),
    mandate_version_id: z.uuid(),
    predicate_id: z.uuid(),
    event_type: z.enum([
      "PREDICATE_FULFILLED",
      "USER_PREDICATE_CONFIRMED",
      "PREDICATE_CANDIDATE",
      "PROVENANCE_VALIDATED",
      "PREDICATE_SUPERSEDED",
    ]),
    producer_kind: z.enum([
      "DETERMINISTIC_PARSER",
      "USER",
      "AI",
      "SOURCE_VALIDATOR",
    ]),
    actor_kind: z.enum([
      "DETERMINISTIC",
      "USER",
      "RESEARCH_ADAPTER",
      "SOURCE_VALIDATOR",
    ]),
    policy_effect: z.enum(["SELL_ELIGIBLE", "REVIEW_ONLY", "PROVENANCE_ONLY"]),
    source_id: z.uuid(),
    evidence_seal_id: z.uuid(),
    source_span: z.string().min(1).max(4096).nullable(),
    observed_metric: z
      .string()
      .regex(/^[A-Z][A-Z0-9_]{0,63}$/u)
      .nullable(),
    observed_value: decimalMetricA1Schema.nullable(),
    unit: z.string().min(1).max(64).nullable(),
    period: z.string().min(1).max(64).nullable(),
    parser_version: z.string().min(1).max(128).nullable(),
    predicate_schema_version: z.string().min(1).max(128).nullable(),
    actor_id: z.string().min(1).max(128).nullable(),
    reason: z.string().min(1).max(1000).nullable(),
    structured_surface: z.boolean(),
    free_text_only: z.boolean(),
    supersedes_event_id: z.uuid().nullable(),
    created_at: timestampA1Schema,
  })
  .strict();
const predicateDefinitionA1Schema = z
  .object({
    predicate_id: z.uuid(),
    mandate_version_id: z.uuid(),
    predicate_schema_version: z.string().min(1).max(128),
    metric: z.string().regex(/^[A-Z][A-Z0-9_]{0,63}$/u),
    comparison_operator: z.enum(["LT", "LTE", "EQ", "GTE", "GT"]),
    threshold_value: decimalMetricA1Schema,
    expected_unit: z.string().min(1).max(64),
    expected_period: z.string().min(1).max(64),
    approval_state: z.literal("APPROVED"),
    approved_by_kind: z.literal("USER"),
  })
  .strict();
const predicateAuthorityCoreA1Schema = z
  .object({
    definitions: z.array(predicateDefinitionA1Schema).min(1),
    events: z.array(predicateAuthorityEventA1Schema).min(1),
  })
  .strict()
  .superRefine((core, context) => {
    const definitions = new Map(
      core.definitions.map((definition) => [
        `${definition.predicate_id}:${definition.mandate_version_id}`,
        definition,
      ]),
    );
    if (definitions.size !== core.definitions.length) {
      context.addIssue({
        code: "custom",
        path: ["definitions"],
        message:
          "Predicate definitions must be unique within a mandate version",
      });
    }
    const eventIds = new Set<string>();
    const priorEvents = new Map<string, (typeof core.events)[number]>();
    const commandIds = new Set<string>();
    core.events.forEach((event, index) => {
      let valid = false;
      const definition = definitions.get(
        `${event.predicate_id}:${event.mandate_version_id}`,
      );
      if (definition === undefined) {
        context.addIssue({
          code: "custom",
          path: ["events", index, "predicate_id"],
          message: "Must reference an approved exact predicate definition",
        });
      }
      if (
        ["PREDICATE_FULFILLED", "USER_PREDICATE_CONFIRMED"].includes(
          event.event_type,
        ) &&
        event.predicate_schema_version !== definition?.predicate_schema_version
      ) {
        context.addIssue({
          code: "custom",
          path: ["events", index, "predicate_schema_version"],
          message: "Must match the approved predicate schema version",
        });
      }
      if (
        event.event_type === "PREDICATE_FULFILLED" &&
        definition !== undefined
      ) {
        const observed =
          event.observed_value === null
            ? null
            : decimalMetricToMicros(event.observed_value);
        const threshold = decimalMetricToMicros(definition.threshold_value);
        const comparisonHolds =
          observed !== null &&
          event.observed_metric === definition.metric &&
          event.unit === definition.expected_unit &&
          event.period === definition.expected_period &&
          ((definition.comparison_operator === "LT" && observed < threshold) ||
            (definition.comparison_operator === "LTE" &&
              observed <= threshold) ||
            (definition.comparison_operator === "EQ" &&
              observed === threshold) ||
            (definition.comparison_operator === "GTE" &&
              observed >= threshold) ||
            (definition.comparison_operator === "GT" && observed > threshold));
        if (!comparisonHolds) {
          context.addIssue({
            code: "custom",
            path: ["events", index, "observed_value"],
            message: "Must satisfy the approved typed predicate",
          });
        }
      }
      if (
        eventIds.has(event.predicate_authority_event_id) ||
        commandIds.has(event.command_id)
      ) {
        context.addIssue({
          code: "custom",
          path: ["events"],
          message: "Event and command identities must be unique",
        });
      }
      if (
        event.supersedes_event_id !== null &&
        (event.event_type !== "PREDICATE_SUPERSEDED" ||
          !eventIds.has(event.supersedes_event_id) ||
          priorEvents.get(event.supersedes_event_id)?.mandate_version_id !==
            event.mandate_version_id ||
          priorEvents.get(event.supersedes_event_id)?.predicate_id !==
            event.predicate_id ||
          priorEvents.get(event.supersedes_event_id)?.event_type !==
            "PREDICATE_FULFILLED" ||
          Date.parse(
            priorEvents.get(event.supersedes_event_id)?.created_at ?? "",
          ) >= Date.parse(event.created_at))
      ) {
        context.addIssue({
          code: "custom",
          path: ["events", index, "supersedes_event_id"],
          message:
            "Must reference an earlier fulfillment for the exact predicate",
        });
      }
      eventIds.add(event.predicate_authority_event_id);
      priorEvents.set(event.predicate_authority_event_id, event);
      commandIds.add(event.command_id);
      switch (event.event_type) {
        case "PREDICATE_FULFILLED":
          valid =
            event.producer_kind === "DETERMINISTIC_PARSER" &&
            event.actor_kind === "DETERMINISTIC" &&
            event.policy_effect === "SELL_ELIGIBLE" &&
            event.source_span !== null &&
            event.observed_metric !== null &&
            event.observed_value !== null &&
            event.unit !== null &&
            event.period !== null &&
            event.parser_version !== null &&
            event.predicate_schema_version !== null &&
            event.structured_surface &&
            !event.free_text_only &&
            event.supersedes_event_id === null;
          break;
        case "USER_PREDICATE_CONFIRMED":
          valid =
            event.producer_kind === "USER" &&
            event.actor_kind === "USER" &&
            event.policy_effect === "SELL_ELIGIBLE" &&
            event.source_span !== null &&
            event.predicate_schema_version !== null &&
            event.actor_id !== null &&
            event.reason !== null &&
            event.structured_surface &&
            !event.free_text_only &&
            event.supersedes_event_id === null;
          break;
        case "PREDICATE_CANDIDATE":
          valid =
            event.producer_kind === "AI" &&
            event.actor_kind === "RESEARCH_ADAPTER" &&
            event.policy_effect === "REVIEW_ONLY" &&
            event.supersedes_event_id === null;
          break;
        case "PROVENANCE_VALIDATED":
          valid =
            event.producer_kind === "SOURCE_VALIDATOR" &&
            event.actor_kind === "SOURCE_VALIDATOR" &&
            event.policy_effect === "PROVENANCE_ONLY" &&
            event.source_span !== null &&
            event.supersedes_event_id === null;
          break;
        case "PREDICATE_SUPERSEDED":
          valid =
            ["DETERMINISTIC_PARSER", "USER"].includes(event.producer_kind) &&
            ((event.producer_kind === "DETERMINISTIC_PARSER" &&
              event.actor_kind === "DETERMINISTIC") ||
              (event.producer_kind === "USER" &&
                event.actor_kind === "USER")) &&
            event.policy_effect === "REVIEW_ONLY" &&
            event.supersedes_event_id !== null &&
            event.reason !== null;
          break;
      }
      if (event.free_text_only) {
        valid = false;
      } else if (!event.structured_surface) {
        valid =
          valid &&
          event.event_type === "PREDICATE_CANDIDATE" &&
          event.policy_effect === "REVIEW_ONLY";
      }
      if (!valid) {
        context.addIssue({
          code: "custom",
          path: ["events", index],
          message:
            "Producer, audit fields, source surface, and policy effect are invalid",
        });
      }
    });
  });

export const portfolioMandateA1FixtureSchema = z
  .object({
    schema_version: z.literal("portfolio-mandate.a1"),
    stable_identity: stableIdentityA1Schema,
    mandate_version_core: mandateVersionCoreA1Schema,
    position_slice_core: positionSliceCoreA1Schema,
    predicate_authority_core: predicateAuthorityCoreA1Schema,
  })
  .strict()
  .superRefine((fixture, context) => {
    const instrumentIds = new Set(
      fixture.stable_identity.instruments.map(
        (instrument) => instrument.instrument_id,
      ),
    );
    const positions = new Map(
      fixture.position_slice_core.broker_positions.map((position) => [
        position.broker_position_id,
        position,
      ]),
    );
    const evidenceSeals = new Map(
      fixture.stable_identity.evidence_seals.map((seal) => [
        seal.evidence_seal_id,
        seal,
      ]),
    );
    const mandates = new Map(
      fixture.mandate_version_core.mandates.map((mandate) => [
        mandate.mandate_id,
        mandate,
      ]),
    );
    const versions = new Map(
      fixture.mandate_version_core.versions.map((version) => [
        version.mandate_version_id,
        version,
      ]),
    );
    const allocations = new Map(
      fixture.position_slice_core.allocations.map((allocation) => [
        allocation.allocation_id,
        allocation,
      ]),
    );
    const activeByPosition = new Map(
      fixture.position_slice_core.allocations
        .filter((allocation) => allocation.active)
        .map((allocation) => [allocation.broker_position_id, allocation]),
    );

    fixture.mandate_version_core.mandates.forEach((mandate, index) => {
      if (!instrumentIds.has(mandate.instrument_id)) {
        context.addIssue({
          code: "custom",
          path: ["mandate_version_core", "mandates", index, "instrument_id"],
          message: "Must reference a stable instrument_id",
        });
      }
      if (mandate.broker_position_id !== null) {
        const position = positions.get(mandate.broker_position_id);
        if (
          position === undefined ||
          position.instrument_id !== mandate.instrument_id
        ) {
          context.addIssue({
            code: "custom",
            path: [
              "mandate_version_core",
              "mandates",
              index,
              "broker_position_id",
            ],
            message:
              "Must reference a broker position for the exact instrument",
          });
        }
      }
    });
    fixture.position_slice_core.broker_positions.forEach((position, index) => {
      if (!instrumentIds.has(position.instrument_id)) {
        context.addIssue({
          code: "custom",
          path: [
            "position_slice_core",
            "broker_positions",
            index,
            "instrument_id",
          ],
          message: "Must reference a stable instrument_id",
        });
      }
    });
    fixture.position_slice_core.slices.forEach((positionSlice, index) => {
      if (positionSlice.mandate_version_id === null) return;
      const version = versions.get(positionSlice.mandate_version_id);
      const mandate =
        version === undefined ? undefined : mandates.get(version.mandate_id);
      const allocation = allocations.get(positionSlice.allocation_id);
      if (
        mandate === undefined ||
        allocation === undefined ||
        mandate.broker_position_id !== allocation.broker_position_id
      ) {
        context.addIssue({
          code: "custom",
          path: ["position_slice_core", "slices", index, "mandate_version_id"],
          message: "Must bind to the exact allocation broker position",
        });
      }
    });
    fixture.mandate_version_core.activation_commands.forEach(
      (command, index) => {
        const mandate = mandates.get(command.mandate_id);
        const active =
          mandate?.broker_position_id === null || mandate === undefined
            ? undefined
            : activeByPosition.get(mandate.broker_position_id);
        if (
          active === undefined ||
          active.allocation_version !== command.allocation_version
        ) {
          context.addIssue({
            code: "custom",
            path: [
              "mandate_version_core",
              "activation_commands",
              index,
              "allocation_version",
            ],
            message: "Must match the exact active allocation version",
          });
        }
        if (
          active === undefined ||
          active.snapshot_version !== command.broker_snapshot_version
        ) {
          context.addIssue({
            code: "custom",
            path: [
              "mandate_version_core",
              "activation_commands",
              index,
              "broker_snapshot_version",
            ],
            message: "Must match the exact active broker snapshot",
          });
        }
        if (
          active !== undefined &&
          !fixture.position_slice_core.slices.some(
            (positionSlice) =>
              positionSlice.allocation_id === active.allocation_id &&
              positionSlice.mandate_version_id ===
                command.expected_mandate_version_id,
          )
        ) {
          context.addIssue({
            code: "custom",
            path: [
              "mandate_version_core",
              "activation_commands",
              index,
              "expected_mandate_version_id",
            ],
            message: "Must bind an active slice on the exact expected version",
          });
        }
      },
    );
    fixture.predicate_authority_core.definitions.forEach(
      (definition, index) => {
        if (!versions.has(definition.mandate_version_id)) {
          context.addIssue({
            code: "custom",
            path: [
              "predicate_authority_core",
              "definitions",
              index,
              "mandate_version_id",
            ],
            message: "Must reference an exact mandate version",
          });
        }
      },
    );
    fixture.predicate_authority_core.events.forEach((event, index) => {
      if (!versions.has(event.mandate_version_id)) {
        context.addIssue({
          code: "custom",
          path: [
            "predicate_authority_core",
            "events",
            index,
            "mandate_version_id",
          ],
          message: "Must reference an exact mandate version",
        });
      }
      const version = versions.get(event.mandate_version_id);
      const mandate =
        version === undefined ? undefined : mandates.get(version.mandate_id);
      if (
        mandate !== undefined &&
        event.producer_kind === "USER" &&
        event.actor_id !== mandate.owner_actor_id
      ) {
        context.addIssue({
          code: "custom",
          path: ["predicate_authority_core", "events", index, "actor_id"],
          message: "Must match the mandate owner",
        });
      }
      const evidenceSeal = evidenceSeals.get(event.evidence_seal_id);
      if (
        mandate === undefined ||
        evidenceSeal === undefined ||
        evidenceSeal.source_id !== event.source_id ||
        evidenceSeal.instrument_id !== mandate.instrument_id
      ) {
        context.addIssue({
          code: "custom",
          path: [
            "predicate_authority_core",
            "events",
            index,
            "evidence_seal_id",
          ],
          message:
            "Must reference an exact source seal for the mandate instrument",
        });
      }
    });
  });

export type PortfolioMandateA1Fixture = z.infer<
  typeof portfolioMandateA1FixtureSchema
>;
export const portfolioMandatePublicEvidenceA1Schema =
  evidenceIdentitySealA1Schema;
export type PortfolioMandatePublicEvidenceA1 = z.infer<
  typeof portfolioMandatePublicEvidenceA1Schema
>;

export const parsePortfolioMandateA1Fixture = (
  value: unknown,
): PortfolioMandateA1Fixture => portfolioMandateA1FixtureSchema.parse(value);

export const parsePortfolioMandatePublicEvidenceA1 = (
  value: unknown,
): PortfolioMandatePublicEvidenceA1 =>
  portfolioMandatePublicEvidenceA1Schema.parse(value);
