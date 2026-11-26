"""Atlas Quant Lab: point-in-time features, strategies and event-driven research.

The package is deliberately a consumer of the Phase 1-3 contracts. It does not create
evidence, bypass the Temporal Evidence Kernel, or execute code supplied in a research
object. A strategy is a typed declaration; the simulator is the only executor.
"""

from .contracts import STRATEGY_SCHEMA, validate_strategy
from .features import FEATURE_SCHEMA, FeatureEngine
from .simulator import SimulationConfig, run_simulation

__all__ = [
    "FEATURE_SCHEMA",
    "FeatureEngine",
    "STRATEGY_SCHEMA",
    "SimulationConfig",
    "run_simulation",
    "validate_strategy",
]
