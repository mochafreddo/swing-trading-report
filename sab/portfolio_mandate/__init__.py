"""Static A1 Portfolio Mandate contract helpers."""

from .contracts import (
    PortfolioMandateA1Fixture,
    PortfolioMandateContractError,
    validate_portfolio_mandate_a1_fixture,
)
from .outcome_history import (
    OutcomeHistoryContractError,
    OutcomeHistoryT15Result,
    adapt_outcome_history_t15,
    parse_redacted_outcome_history_t15_bytes,
)
from .outcomes import (
    OutcomeProposalO1,
    PortfolioOutcomeContractError,
    PortfolioOutcomeO1Fixture,
    PublicOutcomeProjectionO1,
    append_user_outcome_event,
    project_public_outcome_events,
    propose_outcome_matches,
    validate_execution_lineages_o1,
    validate_portfolio_outcome_o1_fixture,
    validate_public_outcome_projection,
)
from .persistence_rehearsal import (
    PersistencePrototypeDisabledError,
    PortfolioMandatePersistenceT16,
    T16ActivationCommand,
    T16ActivationResult,
    T16DecisionProjection,
    T16RollbackResult,
)

__all__ = [
    "OutcomeHistoryContractError",
    "OutcomeHistoryT15Result",
    "OutcomeProposalO1",
    "PersistencePrototypeDisabledError",
    "PortfolioMandateA1Fixture",
    "PortfolioMandateContractError",
    "PortfolioMandatePersistenceT16",
    "PortfolioOutcomeContractError",
    "PortfolioOutcomeO1Fixture",
    "PublicOutcomeProjectionO1",
    "T16ActivationCommand",
    "T16ActivationResult",
    "T16DecisionProjection",
    "T16RollbackResult",
    "adapt_outcome_history_t15",
    "append_user_outcome_event",
    "parse_redacted_outcome_history_t15_bytes",
    "project_public_outcome_events",
    "propose_outcome_matches",
    "validate_execution_lineages_o1",
    "validate_portfolio_mandate_a1_fixture",
    "validate_portfolio_outcome_o1_fixture",
    "validate_public_outcome_projection",
]
