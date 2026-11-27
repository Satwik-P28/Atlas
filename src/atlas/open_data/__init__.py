"""Atlas Data Engine: rights-aware acquisition of redistributable public data.

The package is deliberately independent of the Atlas evidence schema. It owns a
content-addressed snapshot store and a separate SQLite index, and exposes a narrow
bridge (``atlas.open_data.integration``) for writing selected observations into the
Atlas evidence kernel.
"""

from .rights import RightsClass, RightsDecision, RightsViolation, assert_allowed, evaluate

__all__ = [
    "RightsClass",
    "RightsDecision",
    "RightsViolation",
    "assert_allowed",
    "evaluate",
]
