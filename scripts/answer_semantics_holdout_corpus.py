"""Archive the twelve preselected holdout filings and their XBRL facts. Network step only.

This script never parses a filing, never builds a knowledge database and never runs a resolver.
It downloads the exact bytes named by the frozen plan, records their SHA-256 and provenance, and
writes the committed corpus, facts and source manifest that the later, offline scoring run reads.
Keeping ingestion out of this step is deliberate: no resolver-derived artifact exists while the
gold questions are being authored.

Requires ``ATLAS_SEC_USER_AGENT`` (SEC fair-access policy).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "answer_semantics"
PLAN = FIXTURES / "holdout_plan.json"
CORPUS = FIXTURES / "holdout_corpus.json"
FACTS = FIXTURES / "holdout_facts.json"
MANIFEST = ROOT / "artifacts" / "answer_semantics" / "holdout_source_manifest.json"
SNAPSHOTS = ROOT / "var" / "answer_semantics" / "holdout" / "snapshots"
MAX_BYTES = 60 * 1024 * 1024
#: Same tag allowlist and year window as the development corpus: the two cohorts are checked
#: against the same XBRL concepts, so a difference cannot come from a richer gold vocabulary.
FACT_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
             "NetIncomeLoss", "OperatingIncomeLoss", "Assets", "Liabilities",
             "NetCashProvidedByUsedInOperatingActivities", "GrossProfit")
FACT_YEARS = (2019, 2024)
RIGHTS = ("Access and reuse are permitted under the SEC's published web-site policy (fair access, "
          "no fee, no implication of SEC endorsement). EDGAR filings are prepared and filed by "
          "issuers, not by federal employees, so 17 U.S.C. 105 does not apply and no public-domain "
          "status is asserted. Bytes are archived under var/ (gitignored); only accessions, URLs, "
          "digests and short printed figures are committed.")


def _user_agent() -> str:
    value = (os.environ.get("ATLAS_SEC_USER_AGENT") or "").strip()
    if not value:
        raise SystemExit("ATLAS_SEC_USER_AGENT must be set to a declared identity with a working "
                         "contact (SEC fair access)")
    return value


def _get(url: str, user_agent: str, limit: int | None = None) -> bytes:
    request = Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=120) as response:  # noqa: S310 - fixed sec.gov host
        payload = response.read() if limit is None else response.read(limit + 1)
    if limit is not None and len(payload) > limit:
        raise SystemExit(f"document exceeds the archive limit: {url}")
    return payload


def _submissions(cik: str, user_agent: str) -> dict[str, Any]:
    url = f"https://data.sec.gov/submissions/CIK{str(cik).lstrip('0').zfill(10)}.json"
    return json.loads(_get(url, user_agent).decode("utf-8"))


def _companyfacts(cik: str, user_agent: str) -> dict[str, Any]:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).lstrip('0').zfill(10)}.json"
    return json.loads(_get(url, user_agent).decode("utf-8"))


def _acceptance(filing: dict[str, Any]) -> datetime:
    stamp = str(filing["acceptance_time"]).replace("Z", "+00:00")
    if "." in stamp:
        head, tail = stamp.split(".", 1)
        stamp = head + "+" + tail.split("+", 1)[1] if "+" in tail else head + "+00:00"
    return datetime.fromisoformat(stamp).astimezone(timezone.utc)


def trimmed_facts(payload: dict[str, Any], cik: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for namespace, tags in (payload.get("facts") or {}).items():
        for tag, entry in tags.items():
            if tag not in FACT_TAGS:
                continue
            for unit, rows in (entry.get("units") or {}).items():
                if unit != "USD":
                    continue
                for row in rows:
                    if str(row.get("form", "")).upper() not in {"10-K", "10-K/A"}:
                        continue
                    end = str(row.get("end") or "")
                    if not end[:4].isdigit() or not (FACT_YEARS[0] <= int(end[:4]) <= FACT_YEARS[1]):
                        continue
                    out.append({"cik": str(cik).lstrip("0").zfill(10), "namespace": namespace,
                                "tag": tag, "unit": unit, "start": row.get("start"), "end": end,
                                "fy": row.get("fy"), "fp": row.get("fp"), "form": row.get("form"),
                                "accn": row.get("accn"), "filed": row.get("filed"),
                                "frame": row.get("frame"), "val": row.get("val")})
    out.sort(key=lambda item: (item["tag"], item["end"], str(item["accn"])))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", default=str(PLAN))
    parser.add_argument("--force", action="store_true", help="re-download archived bytes")
    args = parser.parse_args(argv)
    user_agent = _user_agent()
    plan = json.loads(Path(args.plan).read_text())
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)

    filings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    facts: dict[str, list[dict[str, Any]]] = {}
    for item in plan["filings"]:
        cik = str(item["cik"]).lstrip("0").zfill(10)
        if cik not in facts:
            facts[cik] = trimmed_facts(_companyfacts(cik, user_agent), cik)
            print(f"facts {cik}: {len(facts[cik])} 10-K USD rows in window")
            time.sleep(0.15)
        url = item["url"]
        snapshot = SNAPSHOTS / f"{item['accession']}.html"
        if snapshot.exists() and not args.force:
            payload = snapshot.read_bytes()
        else:
            payload = _get(url, user_agent, MAX_BYTES)
            snapshot.write_bytes(payload)
            time.sleep(0.15)
        digest = hashlib.sha256(payload).hexdigest()
        accepted = _acceptance(item)
        availability = (accepted + timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff = (accepted + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        filings.append({
            "key": f"H-{item['cik'][-4:]}-FY{item['period_of_report'][:4]}",
            "issuer": item["issuer"], "cik": cik, "accession": item["accession"],
            "document_name": item["primary_document"], "document_role": "primary_document",
            "period_of_report": item["period_of_report"], "filed_date": item["filed_date"],
            "acceptance_time": item["acceptance_time"], "cutoff": cutoff,
            "primary_document_url": url, "layout": "",
        })
        records.append({
            "key": filings[-1]["key"], "issuer": item["issuer"], "cik": cik,
            "accession": item["accession"], "document_name": item["primary_document"],
            "document_role": "primary_document", "period_of_report": item["period_of_report"],
            "filed_date": item["filed_date"], "acceptance_time": item["acceptance_time"],
            "availability_time": availability, "availability_precision": "acceptance_plus_900s",
            "cutoff": cutoff, "primary_document_url": url, "bytes": len(payload),
            "document_sha256": digest, "snapshot": str(snapshot.relative_to(ROOT)),
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "retrieval": "https://www.sec.gov/Archives (single GET, no retries, fair-access pacing)",
            "rights": "sec_edgar_public_access_terms",
        })
        print(f"archived {item['issuer']:45s} {item['accession']} {len(payload):>9d} bytes {digest[:12]}")

    corpus = {
        "schema": "atlas.answer_semantics.holdout_corpus.v1",
        "description": ("Prospective cohort: the twelve filings frozen in holdout_plan.json. "
                        "Selection, seed and rule are unchanged; this file names the documents "
                        "and their declared statement layout."),
        "rights": RIGHTS,
        "filings": filings,
    }
    CORPUS.write_text(json.dumps(corpus, indent=2) + "\n")
    FACTS.write_text(json.dumps({
        "schema": "atlas.answer_semantics.holdout_facts.v1",
        "source": "https://data.sec.gov/api/xbrl/companyfacts/",
        "tags": list(FACT_TAGS), "years": list(FACT_YEARS),
        "count": sum(len(rows) for rows in facts.values()), "facts": facts,
    }, indent=1, sort_keys=True) + "\n")
    manifest = {
        "schema": "atlas.answer_semantics.holdout_source_manifest.v1",
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plan_commitment": plan["commitment"],
        "snapshots": str(SNAPSHOTS.relative_to(ROOT)),
        "filings": records,
        "xbrl": {"source": "https://data.sec.gov/api/xbrl/companyfacts/",
                 "tags": list(FACT_TAGS), "years": list(FACT_YEARS),
                 "counts": {cik: len(rows) for cik, rows in facts.items()},
                 "digest": hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()},
        "limitations": [
            "Filing bodies are archived under var/ and are never committed.",
            "A byte-faithful rebuild needs network access and ATLAS_SEC_USER_AGENT.",
            "SEC company facts are the independent value authority; printed cells are the geometry authority.",
        ],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {CORPUS.name}, {FACTS.name}, {MANIFEST.name}; {len(records)} filings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
