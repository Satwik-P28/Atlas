#!/usr/bin/env python3
"""Audit the open-data registry, its live endpoints and the transcribed samples.

Offline (default) it validates the registry, rights decisions and snapshot hashes.
``--live`` probes every official endpoint and compares the checked-in Treasury samples
with the provider's current official responses. Live failures are reported, not hidden;
the exit status is non-zero only with ``--strict``.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.adapters import normalise_date  # noqa: E402
from atlas.open_data.engine import AcquisitionEngine  # noqa: E402
from atlas.open_data.registry import Registry, audit_rights, summarize, validate_payload  # noqa: E402
from atlas.open_data.rights import review_is_stale  # noqa: E402

UA = "Atlas-Data-Engine/1.0 (audit; contact: admin@example.org)"
CATALOG = ROOT / "data/open_data/catalog.json"
SAMPLES = ROOT / "data/open_data/samples"
ARTIFACTS = ROOT / "artifacts"


def fetch(url: str, *, max_bytes: int = 2_000_000, timeout: int = 45) -> dict:
    request = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity", "Range": "bytes=0-1048575",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes)
            return {
                "requested_url": url, "final_url": response.geturl(), "status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "content_length": response.headers.get("Content-Length"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "bytes_read": len(data), "head": data[:16].hex(),
            }
    except urllib.error.HTTPError as exc:
        # Some government sites reject a Range request or the probe method with 400/416.
        # Retry once as a plain GET before recording a failure; the licence page is still
        # the evidence, and a Range header is not part of its contract.
        if exc.code in {400, 405, 416}:
            retry = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            try:
                with urllib.request.urlopen(retry, timeout=timeout) as response:
                    data = response.read(max_bytes)
                    return {
                        "requested_url": url, "final_url": response.geturl(), "status": response.status,
                        "content_type": response.headers.get("Content-Type"),
                        "content_length": response.headers.get("Content-Length"),
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                        "bytes_read": len(data), "head": data[:16].hex(),
                        "retried_without_range": True,
                    }
            except Exception as retry_error:  # noqa: BLE001 - the first error is kept as evidence
                return {"requested_url": url, "status": exc.code,
                        "error": f"HTTP {exc.code}; retry: {type(retry_error).__name__}: {retry_error}",
                        "final_url": exc.geturl() if hasattr(exc, "geturl") else url}
        return {"requested_url": url, "status": exc.code, "error": f"HTTP {exc.code}",
                "final_url": exc.geturl() if hasattr(exc, "geturl") else url}
    except Exception as exc:  # noqa: BLE001 - a probe failure is evidence
        return {"requested_url": url, "status": None, "error": f"{type(exc).__name__}: {exc}"}


def _ok(result: dict) -> bool:
    return isinstance(result.get("status"), int) and 200 <= result["status"] < 400


def verify_samples() -> dict:
    report: dict = {"checks": [], "ok": True}
    # --- January 1990 nominal par yields -----------------------------------
    official = fetch("https://home.treasury.gov/system/files/276/yield-curve-rates-1990-2024.csv",
                     max_bytes=8_000_000)
    mapping = {
        "yield_3m_pct": "3 Mo", "yield_6m_pct": "6 Mo", "yield_1y_pct": "1 Yr",
        "yield_2y_pct": "2 Yr", "yield_3y_pct": "3 Yr", "yield_5y_pct": "5 Yr",
        "yield_7y_pct": "7 Yr", "yield_10y_pct": "10 Yr", "yield_30y_pct": "30 Yr",
    }
    check = {"sample": "treasury_yields_1990_01.csv", "source": official.get("requested_url"),
             "status": official.get("status"), "rows": 0, "mismatches": []}
    if _ok(official):
        # Re-fetch without the probe range: the comparison needs the full CSV.
        request = urllib.request.Request(official["requested_url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        source_rows = {}
        for row in reader:
            date_text = (row.get("Date") or "").strip()
            normalised = normalise_date(date_text)
            if normalised and normalised.startswith("1990-01"):
                source_rows[normalised] = row
        with (SAMPLES / "treasury_yields_1990_01.csv").open(newline="") as stream:
            sample_rows = list(csv.DictReader(stream))
        check["rows"] = len(sample_rows)
        check["official_rows_for_month"] = len(source_rows)
        for row in sample_rows:
            official_row = source_rows.get(row["record_date"])
            if official_row is None:
                check["mismatches"].append(f"{row['record_date']}: missing upstream")
                continue
            for sample_field, official_field in mapping.items():
                left = Decimal(row[sample_field])
                right = Decimal(official_row[official_field])
                if left != right:
                    check["mismatches"].append(
                        f"{row['record_date']} {sample_field}: sample={left} official={right}")
        check["ok"] = len(sample_rows) == 21 and not check["mismatches"]
    else:
        check["ok"] = False
        check["mismatches"].append("official CSV unavailable")
    report["checks"].append(check)
    report["ok"] = report["ok"] and check["ok"]

    # --- historical debt ---------------------------------------------------
    check = {"sample": "treasury_historical_debt.csv", "mismatches": []}
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_outstanding"
           "?filter=record_date:eq:2024-09-30")
    result = fetch(url, max_bytes=200_000)
    check["status"] = result.get("status")
    if _ok(result):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
        rows = payload.get("data") or []
        expected = list(csv.DictReader((SAMPLES / "treasury_historical_debt.csv").open()))[0]
        check["source_rows"] = len(rows)
        if not rows:
            check["mismatches"].append("no upstream row for 2024-09-30")
        else:
            for field, source_field in (("debt_outstanding_amt", "debt_outstanding_amt"),):
                if Decimal(expected[field]) != Decimal(rows[0][source_field]):
                    check["mismatches"].append(
                        f"{field}: sample={expected[field]} official={rows[0][source_field]}")
        check["ok"] = not check["mismatches"]
    else:
        check["ok"] = False
        check["mismatches"].append("official API unavailable")
    report["checks"].append(check)
    report["ok"] = report["ok"] and check["ok"]

    # --- daily debt --------------------------------------------------------
    check = {"sample": "treasury_daily_debt.csv", "mismatches": []}
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny"
           "?filter=record_date:eq:2026-11-17")
    result = fetch(url, max_bytes=200_000)
    check["status"] = result.get("status")
    if _ok(result):
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
        rows = payload.get("data") or []
        expected = list(csv.DictReader((SAMPLES / "treasury_daily_debt.csv").open()))[0]
        check["source_rows"] = len(rows)
        if not rows:
            check["mismatches"].append("no upstream row for 2026-11-17")
        else:
            for field in ("debt_held_public_amt", "intragov_hold_amt", "tot_pub_debt_out_amt"):
                if Decimal(expected[field]) != Decimal(rows[0][field]):
                    check["mismatches"].append(
                        f"{field}: sample={expected[field]} official={rows[0][field]}")
        check["ok"] = not check["mismatches"]
    else:
        check["ok"] = False
        check["mismatches"].append("official API unavailable")
    report["checks"].append(check)
    report["ok"] = report["ok"] and check["ok"]
    return report


def legacy_catalog_audit(*, live: bool) -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    rows = []
    for entry in catalog["datasets"]:
        row = {"id": entry["id"], "url": entry["url"], "policy_url": entry.get("policy_url"),
               "rights": entry.get("rights"), "kind": entry.get("kind")}
        if live:
            probe = fetch(entry["url"])
            row.update({"status": probe.get("status"), "ok": _ok(probe),
                        "content_type": probe.get("content_type"),
                        "final_url": probe.get("final_url"), "error": probe.get("error")})
            if _ok(probe) and entry.get("kind") == "zip":
                row["zip_magic"] = probe.get("head", "").startswith("504b0304")
                row["ok"] = row["ok"] and row["zip_magic"]
            if _ok(probe) and entry.get("kind") == "json":
                row["json_head"] = probe.get("head", "")[:2] in {"7b22", "5b22", "7b0a"}
        rows.append(row)
    return {"datasets": len(rows), "rows": rows,
            "failures": [row for row in rows if row.get("ok") is False]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="probe official endpoints")
    parser.add_argument("--samples", action="store_true", help="compare checked-in samples upstream")
    parser.add_argument("--snapshots", action="store_true", help="verify snapshot hashes")
    parser.add_argument("--strict", action="store_true", help="fail on live or audit failures")
    parser.add_argument("--out", default=str(ARTIFACTS / "open_data_audit.json"))
    parser.add_argument("--open-root", default="var/open_data")
    parser.add_argument("--open-db", default="var/open_data/atlas_open_data.db")
    args = parser.parse_args(argv)

    registry = Registry.load()
    payload = registry.payload
    errors = validate_payload(payload)
    decisions = audit_rights(payload)
    publication_classes = {"public_domain", "permissive", "redistributable_conditions"}
    stale = [row for row in decisions if row["review_stale"]
             and row["rights_class"] in publication_classes]
    denied = [row for row in decisions if not row["distribution_allowed"]]
    report: dict = {
        "registry": {"datasets": len(payload["datasets"]), "errors": errors,
                     "summary": summarize(payload), "stale_reviews": len(stale),
                     "distribution_denied": len(denied)},
        "decisions": decisions,
    }
    failures = bool(errors)
    if stale:
        failures = True
    if args.live:
        legacy = legacy_catalog_audit(live=True)
        report["legacy_catalog"] = legacy
        failures = failures or bool(legacy["failures"])
        unique: dict[str, dict] = {}
        for dataset in registry:
            for url in filter(None, [dataset.get("download_endpoint"),
                                     dataset.get("official_source_url"),
                                     dataset.get("license_url")]):
                if url not in unique:
                    owner = dataset.id
                    probe = fetch(url)
                    probe["dataset"] = owner
                    probe["rights_class"] = dataset.rights_class.value
                    unique[url] = probe
        report["endpoints"] = list(unique.values())
        approved = {"public_domain", "permissive", "redistributable_conditions"}
        transient = [
            item for item in unique.values() if not _ok(item)
            and item.get("rights_class") in approved
            and (item.get("status") is None or
                 (isinstance(item.get("status"), int) and item["status"] >= 500))
        ]
        report["endpoint_transient"] = transient
        report["endpoint_failures"] = [
            item for item in unique.values() if not _ok(item)
            and item.get("rights_class") in approved
            and item.get("status") is not None
            and item.get("status") not in {401, 403, 405, 406, 429}
            and not (isinstance(item.get("status"), int) and item["status"] >= 500)
        ]
    if args.live:
        failures = failures or bool(report.get("endpoint_failures"))
    if args.samples:
        report["samples"] = verify_samples()
        failures = failures or not report["samples"]["ok"]
    if args.snapshots:
        engine = AcquisitionEngine(store_root=args.open_root, index_path=args.open_db)
        try:
            report["snapshots"] = engine.verify()
            failures = failures or not report["snapshots"]["ok"]
        finally:
            engine.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in report if key not in {"decisions", "endpoints"}},
                     indent=2, default=str))
    print(f"wrote {out}")
    if args.strict and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
