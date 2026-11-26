"""Atlas Quant: Phase 1 financial data and temporal evidence foundation.

The package is organised around stable domain contracts:

``atlas.core``       Financial domain primitives: identifiers, units, time semantics, concepts.
``atlas.storage``    SQLite persistence, schema migrations, transactional helpers.
``atlas.evidence``   Temporal evidence kernel: immutable observed records, availability
                     semantics, supersession chains, point-in-time selection, provenance.
``atlas.entities``   Issuer / security / listing / identifier master with time-bounded
                     ticker assignments and inspectable resolution logic.
``atlas.market``     Trading calendars, OHLCV bars, corporate actions, derived price views.
``atlas.ingestion``  Provider adapters (SEC EDGAR, CSV market data) isolated from storage.
"""

# PEP 440 form of the release label v0.2.0-beta.1. This attribute is the single source of
# truth: pyproject.toml reads it dynamically, and the HTTP API reports it.
__version__ = "0.2.0b1"
__release_label__ = "v0.2.0-beta.1"

__all__ = ["__version__", "__release_label__"]
