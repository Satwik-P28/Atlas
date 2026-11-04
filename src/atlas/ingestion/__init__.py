"""Provider adapters and orchestration.

Connectors are deliberately thin and quarantined from storage semantics: they fetch
and parse into domain records, and the kernel decides how those records are stored.
"""

from .market_csv import CsvImportResult, import_csv_bars, import_parquet_bars
from .sec_client import FetchResult, SecClient, TokenBucket, decode_json, validate_user_agent
from .sec_companyfacts import CompanyFactsResult, decimal_from_json, parse_companyfacts
from .sec_submissions import FilingInfo, FilingRepository, SubmissionsResult, parse_submissions
from .sec_sync import (
    EXCHANGE_MIC_MAP,
    SecIngestor,
    SyncReport,
    load_fixture_payloads,
    register_fixture_documents,
)

__all__ = [
    "CsvImportResult",
    "CompanyFactsResult",
    "EXCHANGE_MIC_MAP",
    "FetchResult",
    "FilingInfo",
    "FilingRepository",
    "SecClient",
    "SecIngestor",
    "SubmissionsResult",
    "SyncReport",
    "TokenBucket",
    "decimal_from_json",
    "decode_json",
    "import_csv_bars",
    "import_parquet_bars",
    "load_fixture_payloads",
    "parse_companyfacts",
    "parse_submissions",
    "register_fixture_documents",
    "validate_user_agent",
]
