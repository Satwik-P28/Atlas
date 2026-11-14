#!/usr/bin/env python
"""The FOCUS demonstration: one real filing, one proven number, and the attacks it survives.

Runs against an already-built corpus (``scripts/focus_corpus.py``). Everything here is
deterministic given that corpus and produces ``artifacts/focus_demo.json``.

The demonstration shows, in order:

1. one value from a real 10-K, with the cell it came from,
2. the independent recomputation that agreed with the compiler,
3. a research certificate for that value,
4. strict source verification against the original SEC bytes,
5. sixteen tampered certificates that strict verification refuses,
6. three refusals of different kinds: a historical cutoff, a concept the statement does not
   contain, and a resolution the system could not settle.

Run ``python scripts/focus_demo.py --help`` for the evidence options.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research.certificate import (  # noqa: E402
    build_certificate,
    payload_fingerprint,
)
from atlas.research.certificate_verify import (  # noqa: E402
    MANIFEST_SCHEMA,
    TrustedEvidence,
    VerificationLevel,
    build_source_manifest,
    verify,
)
from atlas.research.financial_answers import FinancialAnswerEngine  # noqa: E402
from atlas.research.focus_cases import run_cases  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

DEFAULT_DB = ROOT / "var" / "phase9_6.db"
DEFAULT_SNAPSHOTS = ROOT / "var" / "focus" / "snapshots"
DEFAULT_MANIFEST = ROOT / "artifacts" / "focus_source_manifest.json"
DEFAULT_OUT = ROOT / "artifacts" / "focus_demo.json"


def load_snapshots(directory: Path, accessions: set[str]) -> dict[str, bytes]:
    snapshots: dict[str, bytes] = {}
    for accession in accessions:
        path = directory / f"{accession}.html"
        if path.exists():
            snapshots[accession] = path.read_bytes()
    return snapshots


def mutate(certificate: Any, name: str) -> Any:
    """Return a self-consistent tampered certificate: every certificate-owned hash is recomputed.

    This is the point of the exercise. A tampered certificate that still fails is uninteresting;
    the interesting case is one where the attacker has recomputed everything the certificate owns,
    so that only evidence the certificate does not own can detect the change.
    """
    payload = copy.deepcopy(certificate.payload)
    evidence = payload["evidence"][0]
    if name == "changed_result":
        payload["result"]["value"] = "99999.00"
    elif name == "changed_raw_input":
        evidence["raw"] = _bump(evidence["raw"])
    elif name == "changed_input_and_result":
        payload["evidence"][0]["raw"] = _bump(payload["evidence"][0]["raw"])
        payload["result"]["value"] = _recompute_lookup(payload["evidence"][0]["raw"])
    elif name == "changed_source_fingerprint":
        payload["evidence"][0]["document_sha256"] = "0" * 64
        payload["subject"]["document_sha256"] = "0" * 64
    elif name == "changed_issuer":
        payload["subject"]["issuer_name"] = "UNRELATED INDUSTRIES INC"
        payload["subject"]["issuer_id"] = "ISS-CIK0000000001"
    elif name == "changed_accession":
        payload["subject"]["accession"] = "0000000000-00-000000"
    elif name == "changed_period":
        payload["evidence"][0]["period"] = "1999"
    elif name == "changed_currency":
        payload["evidence"][0]["currency"] = "EUR"
        payload["result"]["currency"] = "EUR"
    elif name == "changed_scale":
        payload["evidence"][0]["scale"] = (payload["evidence"][0]["scale"] or 0) + 3
    elif name == "changed_availability":
        payload["evidence"][0]["availability_time"] = "1999-01-01T00:00:00Z"
    elif name == "changed_coordinates":
        payload["evidence"][0]["row"] = int(payload["evidence"][0]["row"]) + 1
    elif name == "changed_concept":
        payload["evidence"][0]["concept"] = "net_income"
    elif name == "changed_table_fingerprint":
        payload["evidence"][0]["table_sha256"] = "f" * 64
    elif name == "changed_operator":
        payload["computation"]["operator"] = "ratio"
    elif name == "changed_value_scale_consistently":
        # Economic amount multiplied by 1000 without touching the printed text.
        payload["result"]["value"] = str(round(float(payload["result"]["value"]) * 1000, 2))
    elif name == "changed_row_label":
        payload["evidence"][0]["row_label"] = "Other revenue"
    else:
        raise SystemExit(f"unknown mutation: {name}")
    return type(certificate)(payload=payload, fingerprint=payload_fingerprint(payload))


def _bump(raw: str) -> str:
    digits = "".join(character for character in raw if character.isdigit())
    if not digits:
        return raw
    value = int(digits) + 1000
    return f"{value:,}"


def _recompute_lookup(raw: str) -> str:
    digits = "".join(character for character in raw if character.isdigit())
    return f"{int(digits)}.00" if digits else "0.00"


MUTATIONS = [
    "changed_result", "changed_raw_input", "changed_input_and_result",
    "changed_source_fingerprint", "changed_issuer", "changed_accession", "changed_period",
    "changed_currency", "changed_scale", "changed_availability", "changed_coordinates",
    "changed_concept", "changed_table_fingerprint", "changed_operator",
    "changed_value_scale_consistently", "changed_row_label",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--snapshots", default=str(DEFAULT_SNAPSHOTS))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--emit-manifest", action="store_true",
                        help="regenerate the pinned source manifest from the corpus and resolver")
    parser.add_argument("--live-sec", action="store_true",
                        help="authenticate against www.sec.gov instead of local snapshots")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(json.dumps({
            "status": "CORPUS_MISSING",
            "database": str(db_path),
            "remedy": "ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com' "
                      "python scripts/focus_corpus.py --force",
        }, indent=2))
        return 2

    db = Database(db_path)
    results = run_cases(db)
    answered = [result for result in results if result.answered]
    certificates = [build_certificate(db, result.packet, result.bindings) for result in answered]

    bindings = [binding for result in answered for binding in result.bindings]
    manifest_path = Path(args.manifest)
    if args.emit_manifest or not manifest_path.exists():
        manifest = build_source_manifest(db, bindings)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit(f"unexpected manifest schema: {manifest.get('schema')!r}")

    accessions = {certificate.subject["accession"] for certificate in certificates}
    snapshots = {} if args.live_sec else load_snapshots(Path(args.snapshots), accessions)
    evidence = TrustedEvidence(manifest=manifest, snapshots=snapshots, live_sec=args.live_sec)

    verified: list[dict[str, Any]] = []
    for result, certificate in zip(answered, certificates):
        arithmetic = verify(certificate, None)
        strict = verify(certificate, evidence)
        verified.append({
            "case_id": result.case_id,
            "issuer": result.issuer,
            "request": result.request,
            "value": certificate.result["value"],
            "unit": certificate.result["unit"],
            "certificate_fingerprint": certificate.fingerprint,
            "certificate_sha256": _sha256(certificate.to_json()),
            "level_without_evidence": arithmetic.level.value,
            "level_with_trusted_evidence": strict.level.value,
            "source_route": strict.source_route,
            "reasons": strict.reasons,
        })

    primary = certificates[0]
    adversarial: list[dict[str, Any]] = []
    for name in MUTATIONS:
        tampered = mutate(primary, name)
        arithmetic = verify(tampered, None)
        strict = verify(tampered, evidence)
        adversarial.append({
            "mutation": name,
            "self_consistent_after_tamper": strict.certificate_fingerprint == tampered.fingerprint,
            "level_without_evidence": arithmetic.level.value,
            "level_with_trusted_evidence": strict.level.value,
            "rejected": strict.level is VerificationLevel.INVALID,
            "reasons": strict.reasons[:4],
        })

    refusals = [
        {"case_id": result.case_id, "issuer": result.issuer, "request": result.request,
         "classification": result.classification, "reason": result.packet.get("reason"),
         "note": result.note}
        for result in results if not result.answered
    ]

    ambiguity = _ambiguity_probe(db)
    payload = {
        "schema": "atlas.focus.demo.v1",
        "corpus": {
            "database": str(db_path),
            "documents": db.query_one("SELECT COUNT(*) AS n FROM knowledge_document")["n"],
            "manifest": str(manifest_path),
            "evidence_route": "sec_live" if args.live_sec else "snapshot",
            "snapshots_found": len(snapshots),
            "expected_snapshots": len(accessions),
        },
        "answer": verified[0] if verified else None,
        "certificates": verified,
        "adversarial": adversarial,
        "refusals": refusals,
        "ambiguity_probe": ambiguity,
        "cases": [result.as_dict() for result in results],
        "summary": {
            "cases": len(results),
            "answered": len(answered),
            "refused": len(results) - len(answered),
            "certificates_source_verified": sum(
                1 for item in verified
                if item["level_with_trusted_evidence"] == VerificationLevel.SOURCE_VERIFIED.value),
            "primary_certificate": str(Path(args.out).parent / "focus_certificate.json"),
            "certificates_arithmetic_only": sum(
                1 for item in verified
                if item["level_without_evidence"] == VerificationLevel.ARITHMETIC_VERIFIED.value),
            "tamper_attempts": len(adversarial),
            "tamper_rejected": sum(1 for item in adversarial if item["rejected"]),
            "tamper_accepted": sum(1 for item in adversarial if not item["rejected"]),
            "refusal_classes": sorted({item["classification"] for item in refusals}),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    # The certificate is a first-class artifact: the CLI verifies this exact file, so the
    # demonstration and the tool are checking the same bytes rather than two re-serialisations.
    certificate_path = out.parent / "focus_certificate.json"
    certificate_path.write_text(primary.to_json(), encoding="utf-8")
    payload["primary_certificate"] = str(certificate_path)
    db.close()

    if not args.quiet:
        _print_summary(payload)
    return 0


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ambiguity_probe(db: Database) -> dict[str, Any]:
    """Look for a genuine ambiguity in the corpus rather than inventing one.

    If no probe is ambiguous, that is reported as ``not_observed``. Manufacturing an ambiguity
    would make the demonstration look stronger while proving less.
    """
    engine = FinancialAnswerEngine(KnowledgeEngine(db))
    probes = [
        ("JPMORGAN CHASE & CO", "total assets", "2022", "2024-01-01T00:00:00Z"),
        ("3M CO", "net sales", "2022", "2024-01-01T00:00:00Z"),
        ("3M CO", "total assets", "2022", "2024-01-01T00:00:00Z"),
        ("COCA COLA CO", "net operating revenues", "2022", "2023-06-30T00:00:00Z"),
    ]
    for legal_name, metric, period, cutoff in probes:
        row = db.query_one("SELECT issuer_id FROM issuer WHERE legal_name = ?", (legal_name,))
        if row is None:
            continue
        packet = engine.lookup(row["issuer_id"], cutoff, metric=metric, period=period)
        if packet.get("reason") == "metric_ambiguous":
            return {"status": "observed", "issuer": legal_name, "metric": metric,
                    "period": period, "reason": packet["reason"],
                    "context": packet.get("context")}
    return {"status": "not_observed",
            "detail": "no probe produced two surviving candidate values with different amounts"}


def _print_summary(payload: dict[str, Any]) -> None:
    answer = payload["answer"]
    print("=" * 78)
    print("ATLAS FOCUS DEMONSTRATION")
    print("=" * 78)
    print(f"corpus      {payload['corpus']['documents']} ingested 10-K documents")
    print(f"evidence    {payload['corpus']['snapshots_found']}/"
          f"{payload['corpus']['expected_snapshots']} source snapshots, route="
          f"{payload['corpus']['evidence_route']}")
    if answer:
        print()
        print(f"1. ANSWER   {answer['issuer']} {answer['request']}")
        print(f"            value={answer['value']}  unit={answer['unit']}")
        print(f"            certificate {answer['certificate_fingerprint'][:16]}…")
        print(f"            {answer['level_without_evidence']} alone, "
              f"{answer['level_with_trusted_evidence']} with source bytes")
    print()
    print("2. CERTIFICATES")
    for item in payload["certificates"]:
        print(f"            {item['case_id']}  {item['value']:>16}  "
              f"{item['level_with_trusted_evidence']}")
    print()
    print("3. ADVERSARIAL TAMPERING (each certificate recomputed to be self-consistent)")
    for item in payload["adversarial"]:
        mark = "refused" if item["rejected"] else "ACCEPTED"
        print(f"            {mark:>8}  {item['mutation']:<34} {item['level_with_trusted_evidence']}")
    print()
    print("4. REFUSALS")
    for item in payload["refusals"]:
        print(f"            {item['case_id']}  {item['classification']:<32} "
              f"{str(item['reason'])[:44]}")
    print()
    probe = payload["ambiguity_probe"]
    print(f"5. AMBIGUITY  {probe['status']}")
    print()
    summary = payload["summary"]
    print(f"{summary['answered']}/{summary['cases']} answered, {summary['refused']} refused, "
          f"{summary['tamper_rejected']}/{summary['tamper_attempts']} tampered certificates "
          f"refused")


if __name__ == "__main__":
    raise SystemExit(main())
