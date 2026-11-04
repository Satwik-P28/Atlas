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

__version__ = "0.1.0"

__all__ = ["__version__"]
