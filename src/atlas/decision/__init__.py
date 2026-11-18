"""Atlas Decision Research Lab: verified convex decision-making with auditable certificates.

The package is organised around one idea: a decision is only as trustworthy as the evidence
that was available when it was taken, and the effect of *later* evidence on that decision can
be bounded without re-solving it.

Modules
-------
``problem``      canonical convex program, validation, feasibility
``qp``           self-certifying solver: primal candidate, dual bound, KKT residuals
``revision``     evidence revision -> explicit, eligibility-checked perturbation
``certificate``  exact zero-regret certificate and bounded-regret certificate
``baselines``    classical policies and competing regret bounds
``estimators``   sample and Ledoit-Wolf covariance, diagonal loading
``metrics``      regret, turnover, CVaR, moving-block bootstrap
``inventory``    second-domain adapter (capacity allocation)
``experiment``   manifests, dataset digests, append-only trial ledger
"""

from __future__ import annotations

from .baselines import (
    BaselineResult,
    equal_weight,
    mean_cvar,
    mean_variance,
    minimum_variance,
    robust_box,
    single_asset,
    strong_convexity_bound,
)
from .certificate import (
    RevisionCertificate,
    StabilityRadius,
    certify_revision_impact,
    degeneracy_report,
    stability_radius,
)
from .experiment import RunManifest, TrialLedger, array_digest, environment_fingerprint
from .metrics import cvar_historical, decision_regret, moving_block_bootstrap_ci, turnover
from .problem import ConvexDecisionProblem, LinearInequality, check_feasibility, mean_variance_problem
from .qp import DualPoint, QPSolution, derive_multipliers, dual_objective, solve, verify_kkt
from .revision import (
    EvidenceRevision,
    InputSensitivity,
    RevisionCompilation,
    compile_revisions,
    directional_perturbation,
)

__all__ = [
    "BaselineResult",
    "ConvexDecisionProblem",
    "DualPoint",
    "EvidenceRevision",
    "InputSensitivity",
    "LinearInequality",
    "QPSolution",
    "RevisionCertificate",
    "RevisionCompilation",
    "RunManifest",
    "StabilityRadius",
    "TrialLedger",
    "array_digest",
    "certify_revision_impact",
    "check_feasibility",
    "compile_revisions",
    "cvar_historical",
    "decision_regret",
    "degeneracy_report",
    "derive_multipliers",
    "directional_perturbation",
    "dual_objective",
    "environment_fingerprint",
    "equal_weight",
    "mean_cvar",
    "mean_variance",
    "mean_variance_problem",
    "minimum_variance",
    "moving_block_bootstrap_ci",
    "robust_box",
    "single_asset",
    "solve",
    "stability_radius",
    "strong_convexity_bound",
    "turnover",
    "verify_kkt",
]
