#!/usr/bin/env python3
"""Build and validate the machine-readable open-data registry.

The register is authored here so every entry has the same shape and defaults are
explicit. ``--write`` regenerates ``data/open_data/registry.json``; ``--check`` fails
when the committed file drifts from the reviewed source or is invalid.

Rights were reviewed on 2026-11-24 against the linked primary terms. Entries whose
terms could not be confirmed are deliberately ``unverified`` and cannot be downloaded
by an automated public-distribution job.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.registry import validate_payload, summarize, audit_rights  # noqa: E402

TARGET = ROOT / "data/open_data/registry.json"
REVIEW_DATE = "2026-11-24"

SEC_LICENSE = "SEC EDGAR public filing data - issuer-authored electronic filings; factual data"
SEC_TERMS = "https://www.sec.gov/about/webmaster-frequently-asked-questions"
#: Only agency-authored SEC metadata is a 17 USC 105 government work. The bulk filing
#: archives are compilations of issuer-authored documents, so they are no longer
#: classified as categorically public domain.
SEC_ISSUER_AUTHORED_EVIDENCE = (
    "SEC EDGAR bulk archives compile issuer-authored electronic filings. The U.S. "
    "government-work doctrine (17 USC 105) covers agency-authored material, not registrant "
    "documents, so Atlas does not class these archives as public domain. Numeric facts, "
    "identifiers and filing metadata are factual data outside copyright protection "
    "(Feist Publications v. Rural Telephone). Atlas distributes only those factual "
    "extracts; third-party exhibits, incorporated documents and issuer narrative text are "
    "excluded. Attribution to SEC EDGAR is requested as a courtesy."
)
TREASURY_TERMS = "https://www.govinfo.gov/link/uscode/17/105"
BLS_TERMS = "https://www.bls.gov/opub/copyright-information.htm"

BASE = {
    "oversight": "Atlas data rights review",
    "rights_verified_at": REVIEW_DATE,
    "commercial_use": True,
    "redistribution": True,
    "modification": True,
    "attribution_required": False,
    "attribution_text": "",
    "third_party_exclusions": [],
    "geographic_coverage": "United States",
    "historical_coverage": {"start": None, "end": None},
    "update_frequency": "unknown",
    "auth_required": False,
    "expected_size_bytes": None,
    "schema_version": "1",
    "ingestion_status": "discovered",
    "adapter": "archive",
    "formats": ["zip"],
    "acquisition": {},
    "parse": {},
    "notes": "",
}


def ds(**overrides):
    entry = dict(BASE)
    entry.update(overrides)
    entry.setdefault("official_source_url", entry.get("download_endpoint"))
    return entry


def _quarters(start_year: int, end_year: int, end_quarter: int = 4) -> list[tuple[int, int]]:
    values = []
    for year in range(start_year, end_year + 1):
        for quarter in range(1, 5):
            if year == end_year and quarter > end_quarter:
                break
            values.append((year, quarter))
    return values


def _fsds_urls(start_year: int = 2009, start_quarter: int = 2,
               end_year: int = 2026, end_quarter: int = 3) -> list[dict[str, str]]:
    return [
        {"url": f"https://www.sec.gov/files/dera/data/financial-statement-data-sets/{year}q{quarter}.zip",
         "name": f"{year}q{quarter}.zip"}
        for year, quarter in _quarters(start_year, end_year, end_quarter)
        if not (year == start_year and quarter < start_quarter)
    ]


def _insider_urls(start_year: int = 2006, end_year: int = 2026, end_quarter: int = 2) -> list[dict[str, str]]:
    return [
        {"url": f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{quarter}_form345.zip",
         "name": f"{year}q{quarter}_form345.zip"}
        for year, quarter in _quarters(start_year, end_year, end_quarter)
    ]


def _ncen_urls(start_year: int = 2019, end_year: int = 2026, end_quarter: int = 3) -> list[dict[str, str]]:
    return [
        {"url": f"https://www.sec.gov/files/dera/data/form-n-cen-data-sets/{year}q{quarter}_ncen.zip",
         "name": f"{year}q{quarter}_ncen.zip"}
        for year, quarter in _quarters(start_year, end_year, end_quarter)
    ]


def sec_metadata(**overrides):
    """SEC-authored metadata (agency work): public domain."""
    defaults = dict(
        provider="SEC",
        license_name="U.S. federal government work - public domain (17 USC 105)",
        license_url=SEC_TERMS,
        rights_class="public_domain",
        rights_evidence=(
            "Agency-authored SEC metadata is a U.S. Government work prepared by agency "
            "employees; 17 USC 105 places it in the public domain. The SEC webmaster FAQ "
            "permits reuse and asks for courtesy attribution."
        ),
        geographic_coverage="United States",
        authentication={"required": False},
        formats=["zip", "json", "txt"],
    )
    defaults.update(overrides)
    return ds(**defaults)


def sec(**overrides):
    """Issuer-authored SEC filing archives: conditionally redistributable factual data."""
    defaults = dict(
        provider="SEC",
        license_name=SEC_LICENSE,
        license_url=SEC_TERMS,
        rights_class="redistributable_conditions",
        rights_evidence=SEC_ISSUER_AUTHORED_EVIDENCE,
        issuer_authored=True,
        attribution_required=True,
        attribution_text=(
            "Source: U.S. Securities and Exchange Commission, EDGAR. Issuer-authored "
            "filings are reproduced here as factual data; third-party exhibits and "
            "narrative note text are excluded."
        ),
        third_party_exclusions=[],
        geographic_coverage="United States",
        authentication={"required": False},
        formats=["zip", "json", "txt"],
    )
    defaults.update(overrides)
    return ds(**defaults)


def treasury(**overrides):
    defaults = dict(
        provider="US Treasury",
        license_name="U.S. federal government work - public domain (17 USC 105)",
        license_url=TREASURY_TERMS,
        rights_class="public_domain",
        rights_evidence=(
            "Treasury rates and Fiscal Data are published by a U.S. federal agency as "
            "part of its official duties and are public domain in the United States. "
            "The published statistics are agency-produced, not vendor quotes."
        ),
        formats=["csv", "json"],
    )
    defaults.update(overrides)
    return ds(**defaults)


def bls(**overrides):
    defaults = dict(
        provider="BLS",
        license_name="U.S. federal government work - public domain",
        license_url=BLS_TERMS,
        rights_class="public_domain",
        rights_evidence=(
            "BLS states that its material is in the public domain and may be reproduced "
            "without permission; BLS requests credit as the source."
        ),
        attribution_required=True,
        attribution_text="Source: U.S. Bureau of Labor Statistics",
        formats=["tsv", "text"],
    )
    defaults.update(overrides)
    return ds(**defaults)


DATASETS = [
    # ------------------------------------------------------------------ SEC
    sec(
        id="sec.companyfacts", title="SEC EDGAR company facts (XBRL)",
        description="Every XBRL fact reported by every EDGAR registrant, grouped by taxonomy, tag and unit.",
        official_source_url="https://www.sec.gov/edgar/sec-api-documentation",
        download_endpoint="https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip",
        historical_coverage={"start": "2009-01-01", "end": None},
        update_frequency="daily", expected_size_bytes=1_430_000_000,
        ingestion_status="implemented", adapter="sec_companyfacts",
        acquisition={"kind": "bulk", "filename": "companyfacts.zip", "max_bytes": 2_000_000_000,
                     "conditional": True, "allowed_redirect_hosts": ["www.sec.gov"]},
        parse={"max_entities": 0, "extract_observations": True, "max_observations": 2_000_000,
               "observation_limit_applied": 2_000_000, "concepts": []},
        notes=("Bulk archive; the full fact census is counted by streaming without loading the "
               "archive into memory. Indexed observations are capped explicitly and the cap is "
               "recorded as sampled scope, never presented as a complete typed history."),
    ),
    sec(
        id="sec.submissions", title="SEC EDGAR submissions archive",
        description="Per-CIK filing histories and recent submissions metadata for all EDGAR registrants.",
        official_source_url="https://www.sec.gov/edgar/sec-api-documentation",
        download_endpoint="https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip",
        historical_coverage={"start": "1993-01-01", "end": None},
        update_frequency="daily", expected_size_bytes=1_580_000_000,
        ingestion_status="implemented", adapter="sec_submissions",
        acquisition={"kind": "bulk", "filename": "submissions.zip", "max_bytes": 2_200_000_000,
                     "conditional": True, "allowed_redirect_hosts": ["www.sec.gov"],
                     "archive_limits": {"max_members": 1_500_000, "max_total_bytes": 32_000_000_000}},
        parse={"max_entities": 0},
    ),
    sec_metadata(
        id="sec.company_tickers", title="SEC company tickers and exchange mapping",
        description="Official CIK/ticker/exchange mapping published by the SEC.",
        download_endpoint="https://www.sec.gov/files/company_tickers_exchange.json",
        historical_coverage={"start": "2020-01-01", "end": None},
        update_frequency="daily", expected_size_bytes=5_000_000,
        ingestion_status="implemented", adapter="archive", formats=["json"],
        acquisition={"kind": "bulk", "filename": "company_tickers_exchange.json", "max_bytes": 50_000_000},
    ),
    sec(
        id="sec.financial_statement_data_sets", title="SEC quarterly Financial Statement Data Sets",
        description="Quarterly structured numeric data extracted from XBRL filings (sub/num/pre/tag).",
        official_source_url="https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets",
        download_endpoint="https://www.sec.gov/files/dera/data/financial-statement-data-sets/2009q2.zip",
        historical_coverage={"start": "2009-04-01", "end": "2026-09-30"},
        update_frequency="quarterly", expected_size_bytes=3_000_000_000,
        ingestion_status="implemented", adapter="sec_financial_statements",
        acquisition={"kind": "url_series", "urls": _fsds_urls(), "max_bytes": 8_000_000_000,
                     "conditional": False, "allowed_redirect_hosts": ["www.sec.gov"]},
        parse={"count_members": ["sub.txt"]},
        notes=("One snapshot holds every published quarter from 2009 Q2 onward. The census counts "
               "submission rows in sub.txt; num.txt numeric rows are retained in the raw archives "
               "but not re-counted, and that scope restriction is recorded."),
    ),
    sec(
        id="sec.notes_data_sets", title="SEC Financial Statement Notes Data Sets",
        description="Monthly structured note disclosures extracted from XBRL filings.",
        official_source_url="https://www.sec.gov/data-research/sec-markets-data/financial-statement-notes-data-sets",
        download_endpoint="https://www.sec.gov/files/dera/data/financial-statement-notes-data-sets/2026_10_notes.zip",
        historical_coverage={"start": "2009-01-01", "end": "2026-10-31"},
        update_frequency="monthly", expected_size_bytes=150_000_000,
        ingestion_status="implemented", adapter="sec_financial_statements",
        acquisition={"kind": "bulk", "filename": "2026_10_notes.zip", "max_bytes": 1_000_000_000},
        third_party_exclusions=["issuer-authored note narrative and embedded exhibits"],
        exclusions_cleared=False,
        notes="Numeric note facts are redistributable; the narrative text is excluded, so the raw "
              "archive is not published until an extract-only package is produced.",
    ),
    sec(
        id="sec.insider_transactions", title="SEC Forms 3, 4 and 5 data sets",
        description="Structured insider ownership and transaction reports.",
        official_source_url="https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets",
        download_endpoint="https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2006q1_form345.zip",
        historical_coverage={"start": "2006-01-01", "end": "2026-09-30"},
        update_frequency="quarterly", expected_size_bytes=2_500_000_000,
        ingestion_status="implemented", adapter="sec_financial_statements",
        acquisition={"kind": "url_series", "urls": _insider_urls(), "max_bytes": 6_000_000_000,
                     "conditional": False, "allowed_redirect_hosts": ["www.sec.gov"]},
        notes="One snapshot holds every published quarterly Form 3/4/5 archive.",
    ),
    sec(
        id="sec.form13f", title="SEC Form 13F data sets",
        description="Structured institutional investment manager holdings reports.",
        official_source_url="https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
        download_endpoint="https://www.sec.gov/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip",
        historical_coverage={"start": "2013-05-01", "end": "2026-05-31"},
        update_frequency="quarterly", expected_size_bytes=25_000_000,
        ingestion_status="implemented", adapter="sec_financial_statements",
        acquisition={"kind": "bulk", "filename": "01mar2026-31may2026_form13f.zip", "max_bytes": 500_000_000},
    ),
    sec(
        id="sec.form_n_port", title="SEC Form N-PORT data sets",
        description="Monthly registered fund portfolio holdings.",
        official_source_url="https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets",
        download_endpoint="https://www.sec.gov/files/dera/data/form-n-port-data-sets/2026q3_nport.zip",
        historical_coverage={"start": "2019-04-01", "end": "2026-09-30"},
        update_frequency="quarterly", expected_size_bytes=200_000_000,
        ingestion_status="implemented", adapter="sec_financial_statements",
        acquisition={"kind": "bulk", "filename": "2026q3_nport.zip", "max_bytes": 1_000_000_000},
    ),
    sec(
        id="sec.form_n_cen", title="SEC Form N-CEN data sets",
        description="Annual census reports by registered investment companies.",
        official_source_url="https://www.sec.gov/data-research/sec-markets-data/form-n-cen-data-sets",
        download_endpoint="https://www.sec.gov/files/dera/data/form-n-cen-data-sets/2019q1_ncen.zip",
        historical_coverage={"start": "2019-01-01", "end": "2026-09-30"},
        update_frequency="quarterly", expected_size_bytes=700_000_000,
        ingestion_status="implemented", adapter="sec_financial_statements",
        acquisition={"kind": "url_series", "urls": _ncen_urls(), "max_bytes": 2_500_000_000,
                     "conditional": False, "allowed_redirect_hosts": ["www.sec.gov"]},
        notes="One snapshot holds every published quarterly N-CEN archive.",
    ),
    sec_metadata(
        id="sec.enforcement_actions", title="SEC enforcement actions",
        description="Regulatory enforcement actions and litigation releases.",
        official_source_url="https://www.sec.gov/enforcement-litigation/enforcement-actions",
        download_endpoint=None, license_name="U.S. federal government work - public domain",
        rights_class="unverified", rights_verified_at=None,
        rights_evidence="No stable machine-readable bulk endpoint was confirmed on 2026-11-24.",
        commercial_use=False, redistribution=False, modification=True,
        ingestion_status="discovered", adapter="archive", formats=["html"],
        notes="Excluded from automated acquisition until a stable official download is documented.",
    ),
    # ------------------------------------------------------------------ banking
    ds(
        id="fdic.institutions", provider="FDIC", title="FDIC BankFind institutions",
        description="Institution directory: charter, location, regulator, identifiers and status.",
        official_source_url="https://banks.data.fdic.gov/docs/",
        download_endpoint="https://api.fdic.gov/banks/institutions",
        license_name="U.S. federal government work - public domain",
        license_url="https://www.fdic.gov/about/website-policies",
        rights_class="public_domain",
        rights_evidence="FDIC is a U.S. federal agency; its public data is a government work and the FDIC website policy permits reuse.",
        historical_coverage={"start": "1934-01-01", "end": None}, update_frequency="quarterly",
        ingestion_status="implemented", adapter="json_api", formats=["json"],
        acquisition={"kind": "json_api", "page_size": 1000, "max_pages": 20, "max_bytes": 200_000_000,
                     "params": {"format": "json"}},
        parse={"data_path": "data", "record_wrapper": "data", "id_field": "CERT",
               "date_field": "ENDEFYMD", "value_fields": []},
    ),
    ds(
        id="fdic.financials", provider="FDIC", title="FDIC BankFind quarterly financials",
        description="Reported bank financial statements and ratios from Call Reports.",
        official_source_url="https://banks.data.fdic.gov/docs/",
        download_endpoint="https://api.fdic.gov/banks/financials",
        license_name="U.S. federal government work - public domain",
        license_url="https://www.fdic.gov/about/website-policies",
        rights_class="public_domain",
        rights_evidence="FDIC public API; government work and website policy permits reuse. No personal data is collected.",
        historical_coverage={"start": "1984-01-01", "end": None}, update_frequency="quarterly",
        ingestion_status="implemented", adapter="json_api", formats=["json"],
        acquisition={"kind": "json_api", "page_size": 1000, "max_pages": 5, "max_bytes": 200_000_000,
                     "params": {"format": "json", "sort_by": "REPDTE", "sort_order": "DESC"}},
        parse={"data_path": "data", "record_wrapper": "data", "id_field": "CERT",
               "date_field": "REPDTE",
               "value_fields": ["ASSET", "DEP", "NETINC", "LNLSNET", "EQTOT"]},
        notes="The registry target is the most recent reported quarter; the API is the source of record.",
    ),
    ds(
        id="ffiec.call_reports", provider="FFIEC", title="FFIEC Call Report bulk data",
        description="Quarterly Call Report financial data for U.S. banks.",
        official_source_url="https://cdr.ffiec.gov/public/PWS/DownloadBulkData.aspx",
        download_endpoint=None,
        license_name="U.S. federal government work - public domain", license_url="https://www.ffiec.gov/",
        rights_class="public_domain",
        rights_evidence="FFIEC is a U.S. government interagency body; Call Report data is a government work.",
        historical_coverage={"start": "2001-01-01", "end": None}, update_frequency="quarterly",
        ingestion_status="blocked", adapter="archive", formats=["zip"],
        notes="Bulk download requires an interactive form postback; no stable anonymous direct URL is documented.",
    ),
    ds(
        id="fed.fr_y9c", provider="Federal Reserve Board", title="FR Y-9C bank holding company statements",
        description="Consolidated financial statements for bank holding companies.",
        official_source_url="https://www.federalreserve.gov/apps/reportforms/reportdetail.aspx?sOoYJ+5BzDaNECN9d5bFdg==",
        download_endpoint=None,
        license_name="U.S. federal government work - public domain", license_url=TREASURY_TERMS,
        rights_class="public_domain",
        rights_evidence="Federal Reserve Board public statistical releases are U.S. government works.",
        historical_coverage={"start": "1986-01-01", "end": None}, update_frequency="quarterly",
        ingestion_status="blocked", adapter="archive", formats=["html", "csv"],
        notes="The data download endpoint was not confirmed; the report form page is not a bulk file.",
    ),
    # ------------------------------------------------------------------ identifiers / procurement
    ds(
        id="gleif.lei_records", provider="GLEIF", title="GLEIF LEI records",
        description="Legal Entity Identifier records with entity and parent relationships.",
        official_source_url="https://www.gleif.org/en/lei-data/gleif-api",
        download_endpoint="https://api.gleif.org/api/v1/lei-records",
        license_name="CC0 1.0 Universal (Public Domain Dedication)",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        rights_class="permissive",
        rights_evidence="GLEIF publishes the LEI golden copy and API under CC0 1.0; attribution is requested but not legally required.",
        attribution_required=True, attribution_text="LEI data: Global Legal Entity Identifier Foundation (GLEIF), CC0 1.0",
        geographic_coverage="Global", historical_coverage={"start": "2012-01-01", "end": None},
        update_frequency="daily", ingestion_status="implemented", adapter="json_api", formats=["json"],
        acquisition={"kind": "json_api", "page_size": 200, "max_pages": 2, "max_bytes": 10_000_000,
                     "page_param": "page[number]", "page_size_param": "page[size]",
                     "start": 1, "increment": 1, "params": {}},
        parse={"data_path": "data", "id_field": "id",
               "date_field": "attributes.registration.initialRegistrationDate", "value_fields": []},
        notes="Bounded sample acquisition; the full golden copy is a separately versioned archive.",
    ),
    ds(
        id="usaspending.awards", provider="USASpending", title="USASpending federal award data",
        description="Federal contract, grant and other award transactions.",
        official_source_url="https://files.usaspending.gov/award_data_archive/",
        download_endpoint="https://api.usaspending.gov/api/v2/references/toptier_agencies/",
        license_name="U.S. federal government work - public domain", license_url=TREASURY_TERMS,
        rights_class="public_domain",
        rights_evidence="USASpending is an official U.S. government system of record; its data is a government work.",
        historical_coverage={"start": "2008-01-01", "end": None}, update_frequency="daily",
        ingestion_status="implemented", adapter="json_api", formats=["json", "zip"],
        acquisition={"kind": "json_api", "page_size": 100, "max_pages": 1, "max_bytes": 10_000_000, "params": {}},
        parse={"data_path": "results", "id_field": "toptier_code", "value_fields": []},
        notes="Agency reference endpoint validates the API; bulk award archives live at the official file host.",
    ),
    ds(
        id="uspto.patent_bulk", provider="USPTO", title="USPTO patent bulk data",
        description="Patent grants, applications and assignments in bulk.",
        official_source_url="https://data.uspto.gov/bulkdata", download_endpoint=None,
        license_name="U.S. federal government work - public domain",
        license_url=TREASURY_TERMS,
        rights_class="public_domain",
        rights_evidence="USPTO bulk data is published by a U.S. federal agency; the terms page permits reuse of government works.",
        historical_coverage={"start": "1976-01-01", "end": None}, update_frequency="weekly",
        ingestion_status="blocked", adapter="archive", formats=["zip", "xml"],
        notes="The legacy bulkdata host no longer resolves; data.uspto.gov requires selecting a product URL.",
    ),
    # ------------------------------------------------------------------ macro
    treasury(
        id="treasury.nominal_yields", title="Treasury nominal par yield curve rates",
        description="Daily Treasury par yield curve rates by tenor.",
        official_source_url="https://home.treasury.gov/interest-rates-data-csv-archive/",
        download_endpoint="https://home.treasury.gov/system/files/276/yield-curve-rates-1990-2024.csv",
        historical_coverage={"start": "1990-01-02", "end": "2024-12-31"}, update_frequency="daily",
        expected_size_bytes=3_000_000, ingestion_status="implemented", adapter="tabular",
        formats=["csv"], acquisition={"kind": "bulk", "filename": "yield-curve-rates-1990-2024.csv",
                                     "max_bytes": 20_000_000},
        parse={"mode": "wide", "date_column": "Date", "unit": "percent"},
    ),
    treasury(
        id="treasury.bill_rates", title="Treasury bill rates",
        description="Daily Treasury bill discount and coupon-equivalent rates.",
        official_source_url="https://home.treasury.gov/interest-rates-data-csv-archive/",
        download_endpoint="https://home.treasury.gov/system/files/276/bill-rates-2002-2024.csv",
        historical_coverage={"start": "2002-01-02", "end": "2024-12-31"}, update_frequency="daily",
        expected_size_bytes=1_500_000, ingestion_status="implemented", adapter="tabular",
        formats=["csv"], acquisition={"kind": "bulk", "filename": "bill-rates-2002-2024.csv",
                                     "max_bytes": 20_000_000},
        parse={"mode": "wide", "date_column": "Date", "unit": "percent"},
    ),
    treasury(
        id="treasury.long_term_rates", title="Treasury long-term rates",
        description="Daily Treasury long-term rate series.",
        official_source_url="https://home.treasury.gov/interest-rates-data-csv-archive/",
        download_endpoint="https://home.treasury.gov/system/files/276/long-term-rates-2000-2024.csv",
        historical_coverage={"start": "2000-01-03", "end": "2024-12-31"}, update_frequency="daily",
        expected_size_bytes=1_000_000, ingestion_status="implemented", adapter="tabular",
        formats=["csv"], acquisition={"kind": "bulk", "filename": "long-term-rates-2000-2024.csv",
                                     "max_bytes": 20_000_000},
        parse={"mode": "wide", "date_column": "Date", "unit": "percent"},
    ),
    treasury(
        id="treasury.real_yields", title="Treasury real par yield curve rates",
        description="Daily Treasury real par yield curve rates (TIPS).",
        official_source_url="https://home.treasury.gov/interest-rates-data-csv-archive/",
        download_endpoint="https://home.treasury.gov/system/files/276/par-real-yield-curve-rates-2003-2024.csv",
        historical_coverage={"start": "2003-01-02", "end": "2024-12-31"}, update_frequency="daily",
        expected_size_bytes=1_000_000, ingestion_status="implemented", adapter="tabular",
        formats=["csv"], acquisition={"kind": "bulk", "filename": "par-real-yield-curve-rates-2003-2024.csv",
                                     "max_bytes": 20_000_000},
        parse={"mode": "wide", "date_column": "Date", "unit": "percent"},
    ),
    treasury(
        id="treasury.real_long_term_rates", title="Treasury real long-term rates",
        description="Daily Treasury real long-term rate series.",
        official_source_url="https://home.treasury.gov/interest-rates-data-csv-archive/",
        download_endpoint="https://home.treasury.gov/system/files/276/real-long-term-rates-2000-2024.csv",
        historical_coverage={"start": "2000-01-03", "end": "2024-12-31"}, update_frequency="daily",
        expected_size_bytes=1_000_000, ingestion_status="implemented", adapter="tabular",
        formats=["csv"], acquisition={"kind": "bulk", "filename": "real-long-term-rates-2000-2024.csv",
                                     "max_bytes": 20_000_000},
        parse={"mode": "wide", "date_column": "Date", "unit": "percent"},
    ),
    treasury(
        id="treasury.debt_to_penny", title="Treasury debt to the penny",
        description="Daily total public debt outstanding, by component.",
        official_source_url="https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
        download_endpoint="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny",
        historical_coverage={"start": "1993-04-01", "end": None}, update_frequency="daily",
        expected_size_bytes=8_000_000, ingestion_status="implemented", adapter="fiscal_api",
        formats=["json"], acquisition={"kind": "fiscal_api", "page_size": 1000, "max_bytes": 200_000_000},
        parse={"date_field": "record_date", "value_fields": ["tot_pub_debt_out_amt"], "unit": "USD"},
    ),
    treasury(
        id="treasury.debt_outstanding", title="Treasury historical debt outstanding",
        description="Historical U.S. debt outstanding by debt type.",
        official_source_url="https://fiscaldata.treasury.gov/datasets/historical-debt-outstanding/",
        download_endpoint="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_outstanding",
        historical_coverage={"start": "1790-01-01", "end": None}, update_frequency="annual",
        expected_size_bytes=1_000_000, ingestion_status="implemented", adapter="fiscal_api",
        formats=["json"], acquisition={"kind": "fiscal_api", "page_size": 1000, "max_bytes": 50_000_000},
        parse={"date_field": "record_date", "value_fields": ["debt_outstanding_amt"], "unit": "USD"},
    ),
    treasury(
        id="treasury.auctions", title="Treasury securities auctions",
        description="Auction results for Treasury bills, notes, bonds and TIPS.",
        official_source_url="https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/",
        download_endpoint="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query",
        historical_coverage={"start": "1973-01-01", "end": None}, update_frequency="daily",
        expected_size_bytes=30_000_000, ingestion_status="implemented", adapter="fiscal_api",
        formats=["json"], acquisition={"kind": "fiscal_api", "page_size": 1000, "max_bytes": 300_000_000},
        parse={"date_field": "auction_date", "value_fields": ["total_accepted", "offering_amt"], "unit": "USD"},
    ),
    treasury(
        id="treasury.avg_interest_rates", title="Treasury average interest rates on federal debt",
        description="Average interest rates on interest-bearing federal debt by security class.",
        official_source_url="https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/",
        download_endpoint="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates",
        historical_coverage={"start": "2001-01-01", "end": None}, update_frequency="monthly",
        expected_size_bytes=5_000_000, ingestion_status="implemented", adapter="fiscal_api",
        formats=["json"], acquisition={"kind": "fiscal_api", "page_size": 1000, "max_bytes": 100_000_000},
        parse={"date_field": "record_date", "value_fields": ["avg_int_rate"], "unit": "percent"},
    ),
    bls(
        id="bls.cpi_current", title="BLS CPI current series data",
        description="Current Consumer Price Index observations for all CPI series.",
        official_source_url="https://download.bls.gov/pub/time.series/cu/",
        download_endpoint="https://download.bls.gov/pub/time.series/cu/cu.data.0.Current",
        historical_coverage={"start": "1913-01-01", "end": None}, update_frequency="monthly",
        expected_size_bytes=30_000_000, ingestion_status="implemented", adapter="tabular",
        acquisition={"kind": "bulk", "filename": "cu.data.0.Current", "max_bytes": 500_000_000},
        parse={"mode": "narrow", "series_column": "series_id", "year_column": "year",
               "period_column": "period", "value_column": "value", "unit": "index"},
    ),
    bls(
        id="bls.cpi_series", title="BLS CPI series metadata",
        description="Series catalogue for the Consumer Price Index.",
        official_source_url="https://download.bls.gov/pub/time.series/cu/",
        download_endpoint="https://download.bls.gov/pub/time.series/cu/cu.series",
        historical_coverage={"start": None, "end": None}, update_frequency="monthly",
        ingestion_status="implemented", adapter="archive", formats=["tsv"],
        acquisition={"kind": "bulk", "filename": "cu.series", "max_bytes": 50_000_000},
    ),
    bls(
        id="bls.employment", title="BLS Current Employment Statistics (all series)",
        description="Payroll employment, hours and earnings for all CES series.",
        official_source_url="https://download.bls.gov/pub/time.series/ce/",
        download_endpoint="https://download.bls.gov/pub/time.series/ce/ce.data.0.AllCESSeries",
        historical_coverage={"start": "1939-01-01", "end": None}, update_frequency="monthly",
        expected_size_bytes=500_000_000, ingestion_status="implemented", adapter="tabular",
        acquisition={"kind": "bulk", "filename": "ce.data.0.AllCESSeries", "max_bytes": 1_500_000_000},
        parse={"mode": "narrow", "series_column": "series_id", "year_column": "year",
               "period_column": "period", "value_column": "value", "unit": "varies"},
        notes="CES aggregate files overlap; this target is the all-series file only.",
    ),
    bls(
        id="bls.employment_series", title="BLS CES series metadata",
        description="Series catalogue for Current Employment Statistics.",
        official_source_url="https://download.bls.gov/pub/time.series/ce/",
        download_endpoint="https://download.bls.gov/pub/time.series/ce/ce.series",
        historical_coverage={"start": None, "end": None}, update_frequency="monthly",
        ingestion_status="implemented", adapter="archive", formats=["tsv"],
        acquisition={"kind": "bulk", "filename": "ce.series", "max_bytes": 50_000_000},
    ),
    bls(
        id="bls.labor_force", title="BLS Local Area Unemployment Statistics",
        description="Labor force, employment and unemployment series.",
        official_source_url="https://download.bls.gov/pub/time.series/ln/",
        download_endpoint="https://download.bls.gov/pub/time.series/ln/ln.data.1.AllData",
        historical_coverage={"start": "1976-01-01", "end": None}, update_frequency="monthly",
        expected_size_bytes=500_000_000, ingestion_status="implemented", adapter="tabular",
        acquisition={"kind": "bulk", "filename": "ln.data.1.AllData", "max_bytes": 1_500_000_000},
        parse={"mode": "narrow", "series_column": "series_id", "year_column": "year",
               "period_column": "period", "value_column": "value", "unit": "varies"},
    ),
    bls(
        id="bls.labor_force_series", title="BLS LAUS series metadata",
        description="Series catalogue for Local Area Unemployment Statistics.",
        official_source_url="https://download.bls.gov/pub/time.series/ln/",
        download_endpoint="https://download.bls.gov/pub/time.series/ln/ln.series",
        historical_coverage={"start": None, "end": None}, update_frequency="monthly",
        ingestion_status="implemented", adapter="archive", formats=["tsv"],
        acquisition={"kind": "bulk", "filename": "ln.series", "max_bytes": 50_000_000},
    ),
    ds(
        id="bea.nipa", provider="BEA", title="BEA National Income and Product Accounts",
        description="GDP, income and product account estimates through the BEA API.",
        official_source_url="https://apps.bea.gov/API/docs/index.htm",
        download_endpoint="https://apps.bea.gov/api/data", license_name="U.S. federal government work - public domain",
        license_url="https://www.bea.gov/help/faq/147",
        rights_class="public_domain", rights_evidence="BEA data is produced by a U.S. federal agency and is public domain; the API requires a registered key.",
        auth_required=True, historical_coverage={"start": "1929-01-01", "end": None},
        update_frequency="quarterly", ingestion_status="blocked", adapter="json_api", formats=["json"],
        acquisition={"kind": "json_api", "page_size": 100, "max_pages": 1, "max_bytes": 10_000_000, "params": {}},
        notes="Requires BEA_API_KEY; never embedded in the repository.",
    ),
    ds(
        id="census.acs", provider="US Census Bureau", title="Census American Community Survey",
        description="Social, economic and housing estimates from the ACS.",
        official_source_url="https://www.census.gov/data/developers/data-sets.html",
        download_endpoint="https://api.census.gov/data/2022/acs/acs1",
        license_name="U.S. federal government work - public domain", license_url=TREASURY_TERMS,
        rights_class="public_domain", rights_evidence="Census Bureau data is a U.S. government work; the API now requires a key.",
        auth_required=True, historical_coverage={"start": "2005-01-01", "end": None},
        update_frequency="annual", ingestion_status="blocked", adapter="archive", formats=["json"],
        notes="Requires CENSUS_API_KEY; not acquired anonymously.",
    ),
    ds(
        id="worldbank.wdi_gdp", provider="World Bank", title="World Bank GDP (current US$)",
        description="World Development Indicators GDP series for all countries.",
        official_source_url="https://data.worldbank.org/indicator/NY.GDP.MKTP.CD",
        download_endpoint="https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD",
        license_name="Creative Commons Attribution 4.0 International (CC BY 4.0)",
        license_url="https://datacatalog.worldbank.org/public-licenses",
        rights_class="permissive",
        rights_evidence="World Bank data is licensed CC BY 4.0; commercial use and redistribution are allowed with attribution. Individual datasets may carry third-party terms.",
        attribution_required=True, attribution_text="Source: World Bank, World Development Indicators (CC BY 4.0)",
        third_party_exclusions=["Country data supplied by national statistical agencies may carry their own attribution terms"],
        geographic_coverage="Global", historical_coverage={"start": "1960-01-01", "end": None},
        update_frequency="annual", ingestion_status="implemented", adapter="worldbank", formats=["json"],
        acquisition={"kind": "worldbank", "page_size": 20000, "max_bytes": 50_000_000},
    ),
    ds(
        id="imf.datamapper", provider="IMF", title="IMF DataMapper macroeconomic indicators",
        description="IMF World Economic Outlook and related macro indicators.",
        official_source_url="https://www.imf.org/external/datamapper/",
        download_endpoint="https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH",
        license_name="IMF Copyright and Usage - statistical data",
        license_url="https://www.imf.org/en/about/copyright-and-terms",
        rights_class="redistributable_conditions",
        rights_evidence="IMF permits download, extraction, distribution and derivative works of statistical data with attribution and a statement of material transformation; third-party components may carry separate terms.",
        attribution_required=True, attribution_text="Source: International Monetary Fund, World Economic Outlook",
        third_party_exclusions=["Some statistical products incorporate third-party information"],
        geographic_coverage="Global", historical_coverage={"start": "1980-01-01", "end": None},
        update_frequency="quarterly", ingestion_status="implemented", adapter="archive", formats=["json"],
        acquisition={"kind": "bulk", "filename": "imf_ngdp_rpch.json", "max_bytes": 20_000_000},
        notes="Bounded response snapshot; country-year parsing requires a dedicated adapter.",
    ),
    ds(
        id="oecd.sdmx", provider="OECD", title="OECD statistics (SDMX)",
        description="OECD statistical data via the SDMX API.",
        official_source_url="https://data-explorer.oecd.org/", download_endpoint=None,
        license_name="OECD Terms and Conditions - data reuse",
        license_url="https://www.oecd.org/en/about/terms-conditions.html",
        rights_class="redistributable_conditions",
        rights_evidence="OECD permits extraction, distribution and commercial use with citation, except where specific or third-party restrictions apply.",
        attribution_required=True, attribution_text="Source: OECD (year), dataset name, DOI/URL, accessed date",
        third_party_exclusions=["Datasets marked as third-party owned require separate permission"],
        geographic_coverage="Global", historical_coverage={"start": None, "end": None},
        update_frequency="varies", ingestion_status="blocked", adapter="archive", formats=["xml", "json", "csv"],
        notes="The SDMX endpoint returned HTTP 406 for the tested content negotiation; not automated until an exact dataflow is verified.",
    ),
    ds(
        id="bis.statistics", provider="BIS", title="BIS statistics",
        description="Bank for International Settlements statistical datasets.",
        official_source_url="https://data.bis.org/", download_endpoint=None,
        license_name="BIS terms of permitted use of statistics",
        license_url="https://www.bis.org/about/legal/permitted-use-statistics",
        rights_class="redistributable_conditions",
        rights_evidence="BIS permits unrestricted use with citation, no misleading endorsement, no additional charge to subscribers, and no warranty. No other use is permitted.",
        attribution_required=True, attribution_text="Source: Bank for International Settlements",
        third_party_exclusions=["Data supplied by national authorities may carry separate terms"],
        geographic_coverage="Global", historical_coverage={"start": None, "end": None},
        update_frequency="varies", ingestion_status="blocked", adapter="archive", formats=["csv", "json", "xml"],
        notes="The SDMX API returned HTTP 406 for the tested request; a verified export URL is required.",
    ),
    ds(
        id="ecb.exchange_rates", provider="ECB", title="ECB euro foreign exchange reference rates",
        description="Daily euro reference exchange rates.",
        official_source_url="https://data.ecb.europa.eu/",
        download_endpoint="https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata",
        license_name="ECB reuse policy for ESCB statistics",
        license_url="https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html",
        rights_class="redistributable_conditions",
        rights_evidence="ESCB statistics may be reused free of charge if the source is quoted and the statistics are not modified; sold documents must disclose that the data is free from the ECB.",
        attribution_required=True, attribution_text="Source: ECB statistics",
        modification=False, third_party_exclusions=["Third-party data requires prior permission from the originator"],
        geographic_coverage="Euro area", historical_coverage={"start": "1999-01-04", "end": None},
        update_frequency="daily", ingestion_status="implemented", adapter="tabular", formats=["csv"],
        acquisition={"kind": "bulk", "filename": "ecb_exr.csv", "max_bytes": 50_000_000},
        parse={"mode": "narrow", "date_column": "TIME_PERIOD", "series_column": "KEY",
               "value_column": "OBS_VALUE", "unit": "rate"},
        notes="The endpoint requests CSV via ?format=csvdata; the KEY dimension is preserved as the series key.",
    ),
    ds(
        id="eurostat.hicp", provider="Eurostat", title="Eurostat harmonised index of consumer prices",
        description="HICP annual rate of change for the euro area.",
        official_source_url="https://ec.europa.eu/eurostat/web/hicp",
        download_endpoint="https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr",
        license_name="European Commission reuse decision - Eurostat copyright notice",
        license_url="https://ec.europa.eu/eurostat/en/help/copyright-notice",
        rights_class="redistributable_conditions",
        rights_evidence="Eurostat authorises reuse for commercial and non-commercial purposes provided the source is acknowledged; individual documents may carry exceptions.",
        attribution_required=True, attribution_text="Source: Eurostat",
        third_party_exclusions=["Material listed in Eurostat's exceptions"],
        geographic_coverage="European Union", historical_coverage={"start": "1996-01-01", "end": None},
        update_frequency="monthly", ingestion_status="implemented", adapter="archive", formats=["json"],
        acquisition={"kind": "bulk", "filename": "eurostat_hicp.json", "max_bytes": 300_000_000},
    ),
    ds(
        id="boe.database", provider="Bank of England", title="Bank of England statistical database",
        description="UK monetary and financial statistics, including Bank Rate.",
        official_source_url="https://www.bankofengland.co.uk/boeapps/database/",
        download_endpoint=None,
        license_name="UK Open Government Licence (statistical data)",
        license_url="https://www.bankofengland.co.uk/legal",
        rights_class="redistributable_conditions",
        rights_evidence="The Bank adopts the UK Open Government Licence for statistical data published under its Statistical Code of Practice; the website CSV endpoint returned HTML in testing.",
        attribution_required=True, attribution_text="Source: Bank of England",
        third_party_exclusions=["Database material outside the OGL exception"],
        geographic_coverage="United Kingdom", historical_coverage={"start": "1694-01-01", "end": None},
        update_frequency="daily", ingestion_status="blocked", adapter="archive", formats=["csv"],
        notes="The tested CSV query returned an HTML page, not CSV; not automated.",
    ),
    # ------------------------------------------------------------------ energy / climate / science
    ds(
        id="eia.electricity", provider="EIA", title="EIA electricity bulk data",
        description="U.S. electricity generation, consumption, prices and emissions.",
        official_source_url="https://www.eia.gov/opendata/bulkfiles.php",
        download_endpoint="https://api.eia.gov/bulk/ELEC.zip",
        license_name="U.S. federal government work - public domain",
        license_url="https://www.eia.gov/about/copyrights_reuse.php",
        rights_class="public_domain",
        rights_evidence="EIA states that its data is in the public domain and may be reused; attribution is requested.",
        attribution_required=True, attribution_text="Source: U.S. Energy Information Administration",
        historical_coverage={"start": "2001-01-01", "end": None}, update_frequency="monthly",
        expected_size_bytes=120_000_000, ingestion_status="implemented", adapter="eia_bulk", formats=["zip", "json"],
        acquisition={"kind": "bulk", "filename": "ELEC.zip", "max_bytes": 500_000_000,
                     "allowed_redirect_hosts": ["www.eia.gov"]},
    ),
    ds(
        id="eia.petroleum", provider="EIA", title="EIA petroleum bulk data",
        description="U.S. petroleum supply, disposition, prices and stocks.",
        official_source_url="https://www.eia.gov/opendata/bulkfiles.php",
        download_endpoint="https://api.eia.gov/bulk/PET.zip",
        license_name="U.S. federal government work - public domain",
        license_url="https://www.eia.gov/about/copyrights_reuse.php",
        rights_class="public_domain",
        rights_evidence="EIA public-domain bulk data; attribution requested.",
        attribution_required=True, attribution_text="Source: U.S. Energy Information Administration",
        historical_coverage={"start": "1973-01-01", "end": None}, update_frequency="monthly",
        expected_size_bytes=100_000_000, ingestion_status="implemented", adapter="eia_bulk", formats=["zip", "json"],
        acquisition={"kind": "bulk", "filename": "PET.zip", "max_bytes": 500_000_000,
                     "allowed_redirect_hosts": ["www.eia.gov"]},
    ),
    ds(
        id="eia.natural_gas", provider="EIA", title="EIA natural gas bulk data",
        description="U.S. natural gas production, consumption, storage and prices.",
        official_source_url="https://www.eia.gov/opendata/bulkfiles.php",
        download_endpoint="https://api.eia.gov/bulk/NG.zip",
        license_name="U.S. federal government work - public domain",
        license_url="https://www.eia.gov/about/copyrights_reuse.php",
        rights_class="public_domain",
        rights_evidence="EIA public-domain bulk data; attribution requested.",
        attribution_required=True, attribution_text="Source: U.S. Energy Information Administration",
        historical_coverage={"start": "1973-01-01", "end": None}, update_frequency="monthly",
        expected_size_bytes=100_000_000, ingestion_status="implemented", adapter="eia_bulk", formats=["zip", "json"],
        acquisition={"kind": "bulk", "filename": "NG.zip", "max_bytes": 500_000_000,
                     "allowed_redirect_hosts": ["www.eia.gov"]},
    ),
    ds(
        id="noaa.ghcn_daily", provider="NOAA", title="NOAA GHCN-Daily station observations",
        description="Daily climate observations for a documented station (Central Park, NY).",
        official_source_url="https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/",
        download_endpoint="https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00094728.csv",
        license_name="U.S. federal government work - public domain",
        license_url="https://www.noaa.gov/information-technology/open-data-dissemination",
        rights_class="public_domain",
        rights_evidence="NOAA open data is a U.S. government work and is disseminated for unrestricted reuse.",
        historical_coverage={"start": "1869-01-01", "end": None}, update_frequency="daily",
        expected_size_bytes=10_000_000, ingestion_status="implemented", adapter="tabular", formats=["csv"],
        acquisition={"kind": "bulk", "filename": "USW00094728.csv", "max_bytes": 100_000_000},
        parse={"mode": "wide", "date_column": "DATE", "value_columns": ["TMAX", "TMIN", "PRCP", "SNOW"],
               "unit": "tenths_celsius_or_mm"},
        notes="One station is a registered sample; a full GHCN mirror is a separate, much larger package.",
    ),
    ds(
        id="usgs.mineral_commodity_summaries", provider="USGS", title="USGS Mineral Commodity Summaries",
        description="Annual mineral production and reserve statistics.",
        official_source_url="https://www.usgs.gov/centers/national-minerals-information-center/minerals-yearbook-metals-and-minerals",
        download_endpoint=None,
        license_name="U.S. federal government work - public domain",
        license_url="https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        rights_class="public_domain",
        rights_evidence="USGS publications are U.S. government works; some map data may include third-party content.",
        historical_coverage={"start": "1996-01-01", "end": None}, update_frequency="annual",
        ingestion_status="blocked", adapter="archive", formats=["pdf", "xlsx"],
        notes="The data release is distributed as workbook/PDF files; no stable machine-readable endpoint was confirmed.",
    ),
    ds(
        id="usda.nass_quickstats", provider="USDA", title="USDA NASS Quick Stats",
        description="Agricultural production, prices and stocks.",
        official_source_url="https://quickstats.nass.usda.gov/api",
        download_endpoint="https://quickstats.nass.usda.gov/api/api_GET/",
        license_name="U.S. federal government work - public domain", license_url=TREASURY_TERMS,
        rights_class="public_domain", rights_evidence="USDA NASS data is a U.S. government work; the API requires a key.",
        auth_required=True, historical_coverage={"start": "1850-01-01", "end": None},
        update_frequency="varies", ingestion_status="blocked", adapter="archive", formats=["json", "csv"],
        notes="Requires NASS_API_KEY.",
    ),
    ds(
        id="clinicaltrials.studies", provider="ClinicalTrials.gov", title="ClinicalTrials.gov study records",
        description="Registered clinical study protocols and results.",
        official_source_url="https://clinicaltrials.gov/data-api/api",
        download_endpoint="https://clinicaltrials.gov/api/v2/studies",
        license_name="NLM ClinicalTrials.gov terms and conditions",
        license_url="https://clinicaltrials.gov/about-site/terms-conditions",
        rights_class="redistributable_conditions",
        rights_evidence="NLM makes ClinicalTrials.gov data available for reuse; users must comply with the site terms and may not imply NLM endorsement. Some records include third-party content.",
        attribution_required=True, attribution_text="Source: ClinicalTrials.gov, U.S. National Library of Medicine",
        third_party_exclusions=["Sponsor-supplied documents and third-party content"],
        geographic_coverage="Global", historical_coverage={"start": "2000-01-01", "end": None},
        update_frequency="daily", ingestion_status="implemented", adapter="json_api", formats=["json"],
        acquisition={"kind": "json_api", "page_size": 100, "max_pages": 1, "max_bytes": 10_000_000, "params": {}},
        parse={"data_path": "studies", "id_field": "protocolSection.identificationModule.nctId", "value_fields": []},
        notes="Bounded sample only; cursor pagination via nextPageToken is not yet implemented.",
    ),
    ds(
        id="fda.openfda_drug_events", provider="FDA", title="FDA openFDA drug adverse events",
        description="Adverse event reports submitted to FAERS.",
        official_source_url="https://open.fda.gov/apis/drug/event/",
        download_endpoint="https://api.fda.gov/drug/event.json",
        license_name="U.S. federal government work - public domain",
        license_url="https://open.fda.gov/license/",
        rights_class="public_domain", rights_evidence="openFDA states its data is public domain and may be used freely; reports are voluntary and unverified.",
        historical_coverage={"start": "2004-01-01", "end": None}, update_frequency="quarterly",
        ingestion_status="implemented", adapter="json_api", formats=["json"],
        acquisition={"kind": "json_api", "page_size": 100, "max_pages": 1, "max_bytes": 10_000_000, "params": {}},
        parse={"data_path": "results", "id_field": "safetyreportid", "value_fields": []},
        notes="Bounded sample; openFDA rate limits apply without a key.",
    ),
    ds(
        id="gdelt.events", provider="GDELT", title="GDELT 2.0 event stream",
        description="Global news-derived event records updated every 15 minutes.",
        official_source_url="https://www.gdeltproject.org/data.html",
        download_endpoint="https://data.gdeltproject.org/gdeltv2/lastupdate.txt",
        license_name="GDELT terms of use",
        license_url="https://gdeltproject.org/about.html",
        rights_class="redistributable_conditions",
        rights_evidence="GDELT permits unlimited academic, commercial and governmental use and redistribution with a citation to the project and a link to gdeltproject.org.",
        attribution_required=True, attribution_text="The GDELT Project (gdeltproject.org)",
        geographic_coverage="Global", historical_coverage={"start": "1979-01-01", "end": None},
        update_frequency="15 minutes", ingestion_status="implemented", adapter="archive", formats=["csv", "zip"],
        acquisition={"kind": "bulk", "filename": "gdelt_lastupdate.txt", "max_bytes": 1_000_000},
    ),
    # ------------------------------------------------------------------ derivatives
    ds(
        id="cftc.commitments_of_traders", provider="CFTC", title="CFTC Commitments of Traders historical archive",
        description="Legacy futures-only commitments of traders reports, 1986-2016.",
        official_source_url="https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm",
        download_endpoint="https://www.cftc.gov/files/dea/history/deacot1986_2016.zip",
        license_name="U.S. federal government work - public domain", license_url="https://www.cftc.gov/WebPolicy/index.htm",
        rights_class="public_domain",
        rights_evidence="CFTC reports are U.S. government works; the CFTC web policy permits reuse and asks for credit.",
        attribution_required=True, attribution_text="Source: U.S. Commodity Futures Trading Commission",
        historical_coverage={"start": "1986-01-01", "end": "2016-12-31"}, update_frequency="weekly",
        expected_size_bytes=120_000_000, ingestion_status="implemented", adapter="cftc", formats=["zip", "txt"],
        acquisition={"kind": "bulk", "filename": "deacot1986_2016.zip", "max_bytes": 500_000_000},
    ),
    ds(
        id="cftc.disaggregated", provider="CFTC", title="CFTC disaggregated futures-only reports 2006-2016",
        description="Disaggregated commitments of traders reports.",
        official_source_url="https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm",
        download_endpoint="https://www.cftc.gov/files/dea/history/fut_disagg_txt_hist_2006_2016.zip",
        license_name="U.S. federal government work - public domain", license_url="https://www.cftc.gov/WebPolicy/index.htm",
        rights_class="public_domain", rights_evidence="CFTC government reports; public domain.",
        attribution_required=True, attribution_text="Source: U.S. Commodity Futures Trading Commission",
        historical_coverage={"start": "2006-06-01", "end": "2016-12-31"}, update_frequency="weekly",
        expected_size_bytes=200_000_000, ingestion_status="implemented", adapter="cftc", formats=["zip", "txt"],
        acquisition={"kind": "bulk", "filename": "fut_disagg_txt_hist_2006_2016.zip", "max_bytes": 800_000_000},
    ),
    ds(
        id="cftc.financial_futures", provider="CFTC", title="CFTC financial futures reports 2006-2016",
        description="Financial futures commitments of traders reports.",
        official_source_url="https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm",
        download_endpoint="https://www.cftc.gov/files/dea/history/fin_fut_txt_2006_2016.zip",
        license_name="U.S. federal government work - public domain", license_url="https://www.cftc.gov/WebPolicy/index.htm",
        rights_class="public_domain", rights_evidence="CFTC government reports; public domain.",
        attribution_required=True, attribution_text="Source: U.S. Commodity Futures Trading Commission",
        historical_coverage={"start": "2006-06-01", "end": "2016-12-31"}, update_frequency="weekly",
        expected_size_bytes=150_000_000, ingestion_status="implemented", adapter="cftc", formats=["zip", "txt"],
        acquisition={"kind": "bulk", "filename": "fin_fut_txt_2006_2016.zip", "max_bytes": 500_000_000},
    ),
    # ------------------------------------------------------------------ macro aggregators / excluded
    ds(
        id="fred.series", provider="FRED", title="FRED economic series (local use only)",
        description="Federal Reserve Economic Data series retrieved through the FRED graph endpoint.",
        official_source_url="https://fred.stlouisfed.org/",
        download_endpoint="https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
        license_name="FRED Services Terms of Use",
        license_url="https://fred.stlouisfed.org/legal/terms",
        rights_class="local_use_only",
        rights_evidence=("FRED prohibits scraping/extraction and redistribution of third-party copyrighted "
                         "series, and requires permission from the series owner. Atlas therefore treats FRED "
                         "as a local analysis convenience only; source-of-record agencies are acquired directly."),
        commercial_use=False, redistribution=False, modification=True,
        attribution_required=True, attribution_text="Source: FRED, Federal Reserve Bank of St. Louis",
        historical_coverage={"start": None, "end": None}, update_frequency="varies",
        ingestion_status="blocked", adapter="archive", formats=["csv"],
        notes="Deliberately not acquired or redistributed. Use BLS/BEA/Treasury/Fed source-of-record endpoints.",
    ),
    ds(
        id="market.equity_ohlcv", provider="Various market vendors", title="Redistributable equity OHLCV (not established)",
        description="Candidate historical equity price sources reviewed for public redistribution.",
        official_source_url="https://github.com/Satwik-P28/Atlas", download_endpoint=None,
        license_name="No redistributable licence established",
        license_url=None,
        rights_class="restricted",
        rights_evidence=("Yahoo, Nasdaq, Alpha Vantage, Stooq, exchange feeds and most academic repositories "
                         "grant access, not redistribution. A software licence on a repository does not "
                         "license its data. No public mirror is created from these sources."),
        commercial_use=False, redistribution=False, modification=False,
        geographic_coverage="Global", historical_coverage={"start": None, "end": None},
        update_frequency="none", ingestion_status="blocked", adapter="archive", formats=["not_applicable"],
        notes="Kept in the registry as a negative result so the exclusion is auditable.",
    ),
    ds(
        id="market.crypto_ohlcv", provider="Crypto exchanges", title="Redistributable crypto OHLCV (not established)",
        description="Candidate crypto market data sources reviewed for public redistribution.",
        official_source_url="https://github.com/Satwik-P28/Atlas", download_endpoint=None,
        license_name="Exchange terms not confirmed for redistribution", license_url=None,
        rights_class="unverified",
        rights_evidence=("Exchange public data endpoints are commonly rate-limited and governed by terms "
                         "that do not clearly grant redistribution. No dataset enters a public package."),
        commercial_use=False, redistribution=False, modification=False,
        geographic_coverage="Global", historical_coverage={"start": None, "end": None},
        update_frequency="none", ingestion_status="blocked", adapter="archive", formats=["not_applicable"],
        notes="Negative result retained for the rights audit.",
    ),
    ds(
        id="finra.regulatory_data", provider="FINRA", title="FINRA regulatory data (restricted)",
        description="FINRA market transparency and regulatory datasets.",
        official_source_url="https://www.finra.org/", download_endpoint=None,
        license_name="FINRA market data licensing", license_url="https://www.finra.org/",
        rights_class="restricted",
        rights_evidence="FINRA market data is licensed; free display does not grant redistribution.",
        commercial_use=False, redistribution=False, modification=False,
        geographic_coverage="United States", historical_coverage={"start": None, "end": None},
        update_frequency="none", ingestion_status="blocked", adapter="archive", formats=["not_applicable"],
        notes="Excluded from acquisition and distribution.",
    ),
]


PAYLOAD = {
    "registry_version": 1,
    "reviewed_at": REVIEW_DATE,
    "policy": {
        "default": "deny",
        "publication_classes": ["public_domain", "permissive", "redistributable_conditions"],
        "notes": "Only the three publication classes may enter a distributed package, and only when "
                 "redistribution=true, commercial_use=true, the review is <365 days old and third-party "
                 "exclusions are cleared. Unverified datasets are never acquired by automated public jobs.",
    },
    "datasets": DATASETS,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write registry.json")
    parser.add_argument("--check", action="store_true", help="fail if the committed registry differs")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    errors = validate_payload(PAYLOAD)
    if errors:
        print("registry validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    serialised = json.dumps(PAYLOAD, indent=2, ensure_ascii=False) + "\n"
    if args.write:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_text(serialised, encoding="utf-8")
        print(f"wrote {TARGET} ({len(DATASETS)} datasets)")
    if args.check:
        if not TARGET.exists():
            print(f"missing {TARGET}", file=sys.stderr)
            return 1
        if TARGET.read_text(encoding="utf-8") != serialised:
            print("committed registry differs from the reviewed source; run --write", file=sys.stderr)
            return 1
        print(f"registry is current ({len(DATASETS)} datasets)")
    if args.summary:
        print(json.dumps(summarize(PAYLOAD), indent=2))
        denied = [row for row in audit_rights(PAYLOAD) if not row["distribution_allowed"]]
        print(f"distribution denied for {len(denied)} datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
