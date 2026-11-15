"""The FOCUS demonstration: real filings, a proven number, and the attacks it survives.

Two procedures, deliberately separated:

* ``scripts/focus_build_corpus.py`` — network. Fetches SEC 10-Ks and archives the exact bytes.
* ``scripts/focus_manifest.py``     — pins the source manifest. Explicit, run once, reviewed.
* this script                       — offline replay against the archived bytes. It never fetches,
  and it never manufactures a trust anchor: a missing corpus, manifest or snapshot is reported as
  missing evidence, not regenerated.

Exit codes
----------
0  every contract below held
1  a contract failed: a certificate failed strict verification, a tamper was accepted, an expected
   refusal was missing, or the case outcomes differ from the pinned expectation
2  the demonstration cannot run: dependency, corpus, manifest or snapshot unavailable

The contracts, in order: thirteen cases; ten answered and three refused with three distinct causes;
every answered case reaches ``SOURCE_VERIFIED`` against the pinned manifest and the archived bytes;
every answered case reaches ``ARITHMETIC_VERIFIED`` without evidence; sixteen self-consistent
tampered certificates are all ``INVALID``; the headline attack (change the printed input and the
result together, then re-sign) passes arithmetic-only verification and fails strict verification;
3M FY2022 carries scale 6 and an economic amount of 34,229,000,000.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research.certificate import build_certificate, fingerprint  # noqa: E402
from atlas.research.certificate_verify import (  # noqa: E402
    TrustedEvidence,
    VerificationLevel,
    verify_payload,
)
from atlas.research.focus_cases import CaseResult, run_cases  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

DEFAULT_DB = "var/focus_demo.db"
DEFAULT_SNAPSHOTS = "var/focus/snapshots"
DEFAULT_MANIFEST = "artifacts/focus_source_manifest.json"
DEFAULT_OUT = "artifacts/focus_demo"

EXPECTED_ANSWERED = 10
EXPECTED_REFUSALS = {
    "justified_unanswerability",
    "capability_gap",
    "historical_information_refusal",
}
FLAGSHIP_ISSUER = "3M CO"
FLAGSHIP_INPUT = "34,229"
FLAGSHIP_SCALE = 6
FLAGSHIP_ECONOMIC_AMOUNT = "34229000000"


# ------------------------------------------------------------------ mutators
def _resign(payload: dict[str, Any]) -> dict[str, Any]:
    """Recompute the certificate's own fingerprint so the tampered artifact is self-consistent."""
    body = {key: value for key, value in payload.items() if key != "certificate_fingerprint"}
    payload["certificate_fingerprint"] = fingerprint(body)
    return payload


def _bump(raw: str, by: int = 1000) -> str:
    digits = "".join(character for character in raw if character.isdigit())
    return f"{int(digits) + by:,}" if digits else raw


def _lookup_value(raw: str) -> str:
    digits = "".join(character for character in raw if character.isdigit())
    return str(int(digits)) if digits else "0"


def mutate(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one mutation and re-sign. Every mutation is internally consistent."""
    mutated = copy.deepcopy(payload)
    binding = mutated["input_bindings"][0]
    source = mutated["selected_sources"][0]
    if name == "changed_result":
        mutated["result"]["value"] = "99999.00"
        mutated["result"]["value_exact"] = "99999"
    elif name == "changed_raw_input":
        binding["raw"] = _bump(binding["raw"])
    elif name == "changed_input_and_result":
        # The headline attack: the printed input, the displayed result, the exact value and the
        # economic amount all move together, and the certificate is re-signed.
        binding["raw"] = _bump(binding["raw"])
        binding["value"] = _lookup_value(binding["raw"])
        mutated["result"]["value"] = f"{_lookup_value(binding['raw'])}.00"
        mutated["result"]["value_exact"] = _lookup_value(binding["raw"])
        mutated["result"]["economic_amount"] = str(
            int(_lookup_value(binding["raw"])) * 10 ** int(binding["scale"]))
    elif name == "changed_certificate_fingerprint":
        mutated["certificate_fingerprint"] = "a" * 64
        return mutated  # deliberately not re-signed
    elif name == "changed_source_fingerprint":
        binding["document_sha256"] = "0" * 64
        source["document_sha256"] = "0" * 64
    elif name == "changed_issuer":
        mutated["issuer_identity"]["issuer_id"] = "ISS-CIK0000000001"
        binding["issuer_id"] = "ISS-CIK0000000001"
    elif name == "changed_accession":
        binding["accession"] = "0000000000-00-000000"
        source["accession"] = "0000000000-00-000000"
    elif name == "changed_period":
        binding["period"] = "1999"
    elif name == "changed_currency":
        binding["currency"] = "EUR"
        mutated["result"]["currency"] = "EUR"
    elif name == "changed_scale":
        # Scale and economic amount move together, so the internal consistency checks pass.
        binding["scale"] = int(binding["scale"]) + 3
        mutated["result"]["economic_amount"] = str(
            int(_lookup_value(binding["raw"])) * 10 ** int(binding["scale"]))
    elif name == "changed_availability":
        binding["availability_time"] = "1999-01-01T00:00:00Z"
        source["availability_time"] = "1999-01-01T00:00:00Z"
    elif name == "changed_coordinates":
        binding["row"] = int(binding["row"]) + 1
    elif name == "changed_concept":
        binding["concept"] = "net_income"
    elif name == "changed_table_fingerprint":
        binding["source_table_sha256"] = "f" * 64
        source["source_table_sha256"] = "f" * 64
    elif name == "changed_operator":
        mutated["normalized_requirement"]["operator"] = "ratio"
        mutated["typed_computation"]["operator"] = "ratio"
    elif name == "changed_row_label":
        binding["row_label"] = "Other revenue"
    elif name == "changed_cutoff":
        mutated["information_cutoff"] = "2017-01-01T00:00:00Z"
    else:
        raise SystemExit(f"unknown mutation: {name}")
    return _resign(mutated)


MUTATIONS = (
    "changed_result",
    "changed_raw_input",
    "changed_input_and_result",
    "changed_certificate_fingerprint",
    "changed_source_fingerprint",
    "changed_issuer",
    "changed_accession",
    "changed_period",
    "changed_currency",
    "changed_scale",
    "changed_availability",
    "changed_coordinates",
    "changed_concept",
    "changed_table_fingerprint",
    "changed_operator",
    "changed_row_label",
)


# ------------------------------------------------------------------ plumbing
def _document_identity(db: Database, bindings: list[Any]) -> dict[str, dict[str, Any]]:
    identity: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if binding.document_id in identity:
            continue
        row = db.query_one(
            "SELECT sha256, primary_document_url, form_type FROM knowledge_document"
            " WHERE document_id = ?", (binding.document_id,))
        if row is not None:
            identity[binding.document_id] = dict(row)
    return identity


def _load_snapshots(directory: Path, accessions: set[str]) -> dict[str, bytes]:
    return {accession: (directory / f"{accession}.html").read_bytes()
            for accession in accessions
            if (directory / f"{accession}.html").exists()}


def _issuer_identity(db: Database, issuer_id: str) -> dict[str, Any]:
    row = db.query_one("SELECT cik, legal_name FROM issuer WHERE issuer_id = ?", (issuer_id,))
    return {"cik": row["cik"], "issuer_name": row["legal_name"]} if row else {}


def _certificate_for(db: Database, result: CaseResult) -> dict[str, Any]:
    identity = _document_identity(db, result.bindings)
    first = result.bindings[0]
    return build_certificate(
        research_question=f"{result.issuer}: {result.operator} {result.request}",
        answer=result.packet,
        bindings=result.bindings,
        cutoff=result.cutoff,
        normalized_requirement={
            "operator": result.packet.get("operator"),
            "concept": first.concept,
            "period": first.period,
            "issuer": result.issuer,
        },
        source_documents=identity,
        issuer_identity=_issuer_identity(db, first.issuer_id),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--snapshots", default=DEFAULT_SNAPSHOTS)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--live-sec", action="store_true",
                        help="authenticate against www.sec.gov instead of archived snapshots")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"schema": "atlas.focus.demo.v2", "checks": [], "steps": []}
    checks: list[dict[str, Any]] = report["checks"]

    def check(name: str, passed: bool, detail: Any = None) -> bool:
        checks.append({"check": name, "passed": bool(passed),
                       **({"detail": detail} if detail is not None else {})})
        return bool(passed)

    def finish(code: int, status: str) -> int:
        report["status"] = status
        report["exit_code"] = code
        report["failures"] = [entry["check"] for entry in checks if not entry["passed"]]
        (out_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        if not args.quiet:
            print(json.dumps({
                "status": status,
                "exit": code,
                "failures": report["failures"],
                "report": str(out_dir / "report.json"),
            }, indent=2, sort_keys=True))
        return code

    # --- preconditions: report missing evidence, never manufacture it ---------------------
    database = Path(args.db)
    if not database.exists():
        report["remedy"] = ("ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com' "
                           f"python scripts/focus_build_corpus.py --db {database}")
        return finish(2, "CORPUS_MISSING")
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        report["remedy"] = f"python scripts/focus_manifest.py --db {database} --out {manifest_path}"
        return finish(2, "MANIFEST_MISSING")
    try:
        evidential = TrustedEvidence.from_manifest_file(
            manifest_path, live_sec=args.live_sec,
            user_agent=os.environ.get("ATLAS_SEC_USER_AGENT") or None)
    except Exception as exc:  # noqa: BLE001 - an unreadable manifest is missing evidence
        report["detail"] = str(exc)
        return finish(2, "MANIFEST_UNREADABLE")

    # --- cases --------------------------------------------------------------------------
    db = Database(str(database))
    results = run_cases(db)
    answered = [result for result in results if result.answered]
    refused = [result for result in results if not result.answered]
    report["corpus"] = {
        "database": str(database),
        "documents": db.query_one("SELECT COUNT(*) AS n FROM knowledge_document")["n"],
        "manifest": str(manifest_path),
        "evidence_route": "sec_live" if args.live_sec else "snapshot",
    }
    check("case_count", len(results) == 13, len(results))
    check("answered_count", len(answered) == EXPECTED_ANSWERED, len(answered))
    check("refused_count", len(refused) == 3, len(refused))
    refusal_classes = {result.classification for result in refused}
    check("refusal_classes", refusal_classes == EXPECTED_REFUSALS, sorted(refusal_classes))
    check("no_refusal_scored_as_answer",
          all(result.packet.get("outcome") != "answered" for result in refused))

    certificates = [_certificate_for(db, result) for result in answered]
    if not args.live_sec:
        accessions = {certificate["input_bindings"][0]["accession"] for certificate in certificates}
        evidential.snapshots = _load_snapshots(Path(args.snapshots), accessions)
        check("snapshots_present", len(evidential.snapshots) == len(accessions),
              f"{len(evidential.snapshots)}/{len(accessions)}")

    matrix: list[dict[str, Any]] = []
    for result, certificate in zip(answered, certificates):
        arithmetic = verify_payload(certificate)
        strict = verify_payload(certificate, evidence=evidential)
        matrix.append({
            "case_id": result.case_id,
            "issuer": result.issuer,
            "operator": result.operator,
            "request": result.request,
            "value": certificate["result"]["value"],
            "value_exact": certificate["result"]["value_exact"],
            "economic_amount": certificate["result"]["economic_amount"],
            "scale": certificate["input_bindings"][0]["scale"],
            "currency": certificate["input_bindings"][0]["currency"],
            "raw": certificate["input_bindings"][0]["raw"],
            "accession": certificate["input_bindings"][0]["accession"],
            "certificate_fingerprint": certificate["certificate_fingerprint"],
            "level_without_evidence": arithmetic["level"],
            "level_with_trusted_evidence": strict["level"],
            "source_route": strict["source_route"],
            "reasons": strict["reasons"],
        })
        check(f"strict_verified:{result.case_id}",
              strict["level"] == VerificationLevel.SOURCE_VERIFIED.value, strict["reasons"])
        check(f"arithmetic_verified:{result.case_id}",
              arithmetic["level"] == VerificationLevel.ARITHMETIC_VERIFIED.value,
              arithmetic["reasons"])
    report["verification_matrix"] = matrix

    # --- flagship claim: 3M FY2022 scale and economic amount -----------------------------
    flagship = next((entry for entry in matrix
                     if entry["issuer"] == FLAGSHIP_ISSUER
                     and entry["request"].get("concept") == "revenue"
                     and entry["request"].get("period") == "2022"), None)
    if flagship is None:
        check("flagship_present", False, "3M FY2022 revenue was not answered")
    else:
        check("flagship_raw", flagship["raw"] == FLAGSHIP_INPUT, flagship["raw"])
        check("flagship_scale", flagship["scale"] == FLAGSHIP_SCALE, flagship["scale"])
        check("flagship_economic_amount",
              str(flagship["economic_amount"]) == FLAGSHIP_ECONOMIC_AMOUNT,
              flagship["economic_amount"])
        check("flagship_currency_disclosed", True,
              "currency is not detected from source context; scale is certified, currency is not")
        report["flagship"] = flagship

    # --- refusal evidence ---------------------------------------------------------------
    report["refusals"] = [
        {"case_id": result.case_id, "issuer": result.issuer, "request": result.request,
         "classification": result.classification, "reason": result.packet.get("reason"),
         "note": result.note}
        for result in refused
    ]
    three_m_2018 = next((entry for entry in report["refusals"]
                         if entry["issuer"] == FLAGSHIP_ISSUER
                         and entry["request"].get("period") == "2018"), None)
    check("capability_gap_recorded",
          three_m_2018 is not None and three_m_2018["classification"] == "capability_gap",
          three_m_2018)

    # --- adversarial matrix -------------------------------------------------------------
    if certificates:
        primary = certificates[0]
        primary_path = out_dir / "certificate.json"
        primary_path.write_text(json.dumps(primary, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
        report["primary_certificate"] = str(primary_path)
        raw_tamper: list[dict[str, Any]] = []
        for name in MUTATIONS:
            tampered = mutate(name, primary)
            arithmetic = verify_payload(tampered)
            strict = verify_payload(tampered, evidence=evidential)
            rejected = strict["level"] == VerificationLevel.INVALID.value
            raw_tamper.append({
                "mutation": name,
                "self_consistent": tampered.get("certificate_fingerprint")
                == fingerprint({key: value for key, value in tampered.items()
                                if key != "certificate_fingerprint"}),
                "level_without_evidence": arithmetic["level"],
                "level_with_trusted_evidence": strict["level"],
                "rejected": rejected,
                "reasons": strict["reasons"][:4],
            })
            check(f"tamper_rejected:{name}", rejected, strict["reasons"][:4])
        report["adversarial"] = raw_tamper

        headline = next(entry for entry in raw_tamper
                        if entry["mutation"] == "changed_input_and_result")
        check("headline_attack_passes_arithmetic_only",
              headline["level_without_evidence"] == VerificationLevel.ARITHMETIC_VERIFIED.value,
              headline["level_without_evidence"])
        check("headline_attack_refused_with_evidence",
              headline["level_with_trusted_evidence"] == VerificationLevel.INVALID.value,
              headline["level_with_trusted_evidence"])
        check("tamper_count", len(raw_tamper) == 16, len(raw_tamper))

        (out_dir / "certificates.json").write_text(
            json.dumps(certificates, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report["cases"] = [result.as_dict() for result in results]
    report["claims"] = [
        "Thirteen real-filing cases across Coca-Cola, JPMorgan and 3M; ten answered, three "
        "refused with three distinct causes.",
        "Every answered value reached SOURCE_VERIFIED against a pinned manifest and the archived "
        "original SEC bytes.",
        "Sixteen self-consistent tampered certificates, including the input-and-result attack, "
        "were refused under trusted evidence.",
        "3M FY2022 net sales: printed 34,229, scale 6, economic amount 34,229,000,000 (currency "
        "not detected from source context and therefore not asserted).",
    ]
    db.close()
    code = 0 if all(entry["passed"] for entry in checks) else 1
    return finish(code, "passed" if code == 0 else "failed")


if __name__ == "__main__":
    raise SystemExit(main())
