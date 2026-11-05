"""Atlas Learning Brain: data fabric, features, calibrated forecasts and audits.

The package is deliberately split from the FEC and Quant Lab. It consumes their
contracts and emits typed artifacts; it does not create a second identity system.
"""

from .contracts import (
    FORECAST_SCHEMA,
    LEARNING_SCHEMA,
    MODEL_SCHEMA,
    forecast_document,
    model_document,
)
from .experiments import run_experiment
from .service import LearningService

__all__ = [
    "FORECAST_SCHEMA",
    "LEARNING_SCHEMA",
    "MODEL_SCHEMA",
    "LearningService",
    "forecast_document",
    "model_document",
    "run_experiment",
]
