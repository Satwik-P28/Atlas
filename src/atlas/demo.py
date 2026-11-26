"""Offline end-to-end demonstration.

Everything here runs without network access, using archived SEC payloads plus
clearly-labelled synthetic fixtures. The demonstration is the executable form of the
Phase 1 acceptance tests: each section exercises one system boundary and prints the
evidence it relied on.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from .core.concepts import CONCEPTS
from .core.temporal import AsOfMode, availability_from_instant, iso, iso_date, utcnow
from .entities.master import SecurityMaster
from .evidence.kernel import EvidenceKernel
from .ingestion.market_csv import import_csv_bars
from .ingestion.sec_sync import SecIngestor, load_fixture_payloads, register_fixture_documents
from .market.actions import ActionStore, ActionType, CorporateAction
from .market.adjust import split_adjust, total_return, verify_split_continuity
from .market.bars import BarStore
from .market.calendar import TradingCalendar
from .storage.db import open_database
from .storage.quality import issue_summary
from .storage.sources import ATLAS_SYNTHETIC, SourceRegistry, ensure_default_sources
from .validation import run_validation, summarize

APPLE_CIK = "0000320193"
RESTATEMENT_CIK = "0001999999"
DEMO_ANSWER_CIK = "1900003"
DEMO_ANSWER_ACCESSION = "0000000000-24-000900"
DEMO_ANSWER_CONCEPT = "gross_profit"
DEMO_ANSWER_PERIOD = "2023"

PACKAGED_FIXTURES = Path(__file__).resolve().parent / "_demo_fixtures"


def _default_fixture_root() -> Path:
    """Find the demonstration fixtures for a source checkout or a packaged install.

    A wheel install has no repository ``fixtures/`` directory, so the demo must not depend
    on one: the release build stages the small demonstration subset inside the package.
    The source checkout keeps using the repository copy, which is the single source of
    truth for the committed bytes.
    """
    checkout = Path(__file__).resolve().parents[2] / "fixtures"
    if (checkout / "sec").is_dir():
        return checkout
    if (PACKAGED_FIXTURES / "sec").is_dir():
        return PACKAGED_FIXTURES
    return checkout


@dataclass(slots=True)
class DemoContext:
    db: Any
    fixtures: Path
    stream: Callable[[str], None]
    results: dict[str, Any]

    def say(self, message: str = "") -> None:
        self.stream(message)

    def section(self, title: str) -> None:
        self.say()
        self.say("=" * 78)
        self.say(title)
        self.say("=" * 78)


def run_demo(
    *,
    db_path: str = "var/demo/atlas-demo.db",
    fixture_dir: str | Path | None = None,
    reset: bool = True,
    stream: Callable[[str], None] = print,
) -> dict[str, Any]:
    fixtures = Path(fixture_dir) if fixture_dir else _default_fixture_root()
    path = Path(db_path)
    if reset:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists():
                candidate.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = open_database(path)
    context = DemoContext(db=db, fixtures=fixtures, stream=stream, results={"database": str(path)})
    try:
        ensure_default_sources(db)
        context.say(f"Atlas Phase 1 demonstration - database {path} (schema v{db.schema_version()})")
        _section_company_research(context)
        _section_historical_reconstruction(context)
        _section_identity(context)
        _section_market_and_actions(context)
        _section_financial_xray(context)
        _section_incremental(context)
        _section_financial_answer(context)
        _section_validation(context)
    finally:
        db.close()
    return context.results


# --------------------------------------------------------------------------- #
# A. Company research from real SEC data
# --------------------------------------------------------------------------- #
def _sync_fixture_company(context: DemoContext, directory: Path, cik: str) -> Any:
    submissions, facts, _, _ = load_fixture_payloads(directory, cik)
    submissions_doc, facts_doc = register_fixture_documents(context.db, directory, cik)
    ingestor = SecIngestor(context.db)
    return ingestor.sync_payloads(
        cik,
        submissions_payload=submissions,
        companyfacts_payload=facts,
        submissions_doc_id=submissions_doc,
        companyfacts_doc_id=facts_doc,
        submissions_url=f"fixture://{cik}/submissions.json",
        companyfacts_url=f"fixture://{cik}/companyfacts.json",
    )


def _section_company_research(context: DemoContext) -> None:
    context.section("A. Company research: Apple Inc. (real SEC data, archived payload)")
    directory = context.fixtures / "sec"
    report = _sync_fixture_company(context, directory, APPLE_CIK)
    context.say(f"issuer           : {report.issuer_id}  ({report.legal_name})")
    context.say(f"filings stored   : {report.filings_written}")
    stats = report.companyfacts.get("stats", {})
    context.say(f"XBRL tags seen   : {stats.get('tags_available')}   mapped: {stats.get('tags_mapped')}")
    context.say(f"facts used       : {stats.get('observations_used')}   deduplicated: {stats.get('observations_deduplicated')}")
    context.say(
        f"availability     : exact={stats.get('availability_exact')} "
        f"date-only={stats.get('availability_date')} unknown={stats.get('availability_unknown')}"
    )
    for security in report.securities:
        context.say(f"security         : {security['security_id']} {security['ticker']}@{security['mic']} "
                    f"({security['status']}, confidence {security['confidence']})")

    kernel = EvidenceKernel(context.db)
    issuer_id = report.issuer_id
    result = kernel.as_of(issuer_id, utcnow(), concepts=["revenue", "net_income", "eps_diluted", "assets"])
    context.say()
    context.say(f"{'concept':14} {'period end':12} {'value':>18} {'unit':12} {'accession':22} form")
    for fact in result.facts[-8:]:
        context.say(
            f"{fact.concept:14} {fact.period_end or '':12} {(fact.value or ''):>18} {fact.unit:12} "
            f"{(fact.accession_number or ''):22} {fact.form_type or ''}"
        )
    context.say(f"completeness: {result.completeness}")
    context.results["company_research"] = {
        "issuer_id": issuer_id,
        "filings": report.filings_written,
        "facts": stats.get("observations_used"),
        "securities": report.securities,
        "sample_concepts": [f.concept for f in result.facts],
    }


# --------------------------------------------------------------------------- #
# B. Historical reconstruction across a restatement
# --------------------------------------------------------------------------- #
def _section_historical_reconstruction(context: DemoContext) -> None:
    context.section("B. Historical reconstruction: an amendment must not leak backwards")
    context.say("Fixture: Atlas Synthetic Restatement Corp (synthetic, CIK 1999999).")
    context.say("Q1 2024 revenue was first reported 2024-05-01 at 100,000,000 USD and restated")
    context.say("2024-08-15 in a 10-Q/A at 90,000,000 USD. Both filings are real-shaped SEC payloads.")
    directory = context.fixtures / "sec_restatement"
    report = _sync_fixture_company(context, directory, RESTATEMENT_CIK)
    issuer_id = report.issuer_id
    kernel = EvidenceKernel(context.db)

    before = kernel.as_of(issuer_id, "2024-06-01T00:00:00Z", concepts=["revenue"])
    after = kernel.as_of(issuer_id, "2024-09-01T00:00:00Z", concepts=["revenue"])
    before_fact = next(fact for fact in before.facts if fact.unit == "USD")
    after_fact = next(fact for fact in after.facts if fact.unit == "USD")
    context.say()
    context.say(f"as of 2024-06-01 : {before_fact.value:>12} {before_fact.unit}  "
                f"evidence {before_fact.evidence_id}  accession {before_fact.accession_number}")
    context.say(f"as of 2024-09-01 : {after_fact.value:>12} {after_fact.unit}  "
                f"evidence {after_fact.evidence_id}  accession {after_fact.accession_number}")
    context.say(f"records withheld because they were not yet public at 2024-06-01: {before.excluded_not_yet_available}")
    leaked = before_fact.value == "90000000"
    context.say(f"no look-ahead leakage: {'PASS' if not leaked else 'FAIL'}")

    history = kernel.history(issuer_id, "revenue")
    usd_versions = [record for record in history if record.unit == "USD"]
    context.say()
    context.say("Full disclosure history retained (nothing overwritten):")
    for record in history:
        context.say(f"  {record.evidence_id}  value={record.value_numeric:>10} {record.unit:>3}  "
                    f"available={record.availability_time}  revision={record.revision_kind}  "
                    f"accession={record.accession_number}")
    chain = kernel.lineage(after_fact.evidence_id)
    superseded = [entry for entry in chain if entry["superseded_by"]]
    context.say(f"supersession links: {len(superseded)} "
                f"({', '.join(entry['evidence_id'] + ' -> ' + ','.join(entry['superseded_by']) for entry in superseded)})")

    # Unit discipline: a wrong unit *kind* is rejected; a wrong *currency* is kept
    # separate and never combined.
    stats = report.companyfacts.get("stats", {})
    rejected = stats.get("observations_skipped_unit_mismatch", 0)
    multi_currency = stats.get("multi_currency_concepts", {})
    context.say(f"observations rejected for a non-monetary unit kind: {rejected}")
    context.say(f"concepts reported in multiple currencies (kept separate): {multi_currency}")

    context.results["historical_reconstruction"] = {
        "as_of_2024_06_01": {"value": before_fact.value, "evidence_id": before_fact.evidence_id,
                             "accession": before_fact.accession_number},
        "as_of_2024_09_01": {"value": after_fact.value, "evidence_id": after_fact.evidence_id,
                             "accession": after_fact.accession_number},
        "look_ahead_leak": leaked,
        "withheld": before.excluded_not_yet_available,
        "versions": len(usd_versions),
        "unit_mismatches_rejected": rejected,
        "multi_currency": multi_currency,
    }


# --------------------------------------------------------------------------- #
# C. Security identity across ticker change and ticker reuse
# --------------------------------------------------------------------------- #
def _section_identity(context: DemoContext) -> None:
    context.section("C. Security identity: ticker change, ticker reuse, no silent merges")
    master = SecurityMaster(context.db)
    master.ensure_venue("XNAS", "Nasdaq Global Select Market", country="US", timezone="America/New_York")

    meta = master.register_issuer(legal_name="Meta Platforms Demo Inc.", cik="1900001", entity_type="corporation")
    meta_security = master.ensure_security(meta, class_designation="Class A common stock", currency="USD")
    meta_listing = master.ensure_listing(meta_security, "XNAS", valid_from="2012-05-18", is_primary=True)
    master.assign_ticker(meta_listing, "FB", valid_from="2012-05-18", status="confirmed", confidence=1.0,
                         evidence_note="demo: historical ticker before the 2022 rename")
    change = master.record_ticker_change(meta_security, "META", "2022-06-09",
                                         note="demo: company renamed and changed ticker")

    reuse_issuer = master.register_issuer(legal_name="Unrelated Robotics Demo Corp", cik="1900002")
    reuse_security = master.ensure_security(reuse_issuer, class_designation="common stock", currency="USD")
    reuse_listing = master.ensure_listing(reuse_security, "XNAS", valid_from="2023-01-10", is_primary=True)
    master.assign_ticker(reuse_listing, "FB", valid_from="2023-01-10", status="probable", confidence=0.8,
                         evidence_note="demo: the FB symbol was later reused by a different issuer")

    context.say(f"ticker change recorded: {change['previous_ticker']} closed {change['previous_closed_on']}, "
                f"{change['new_ticker']} from {change['effective_date']}")

    for label, ticker, as_of in (
        ("2021 (before rename)", "FB", "2021-06-01"),
        ("2024 (after reuse)", "FB", "2024-01-01"),
        ("2022-12 (gap between owners)", "FB", "2022-12-01"),
        ("2020 (before rename, META)", "META", "2020-01-01"),
    ):
        resolution = master.resolve_ticker(ticker, as_of=as_of)
        description = (
            f"{resolution.candidates[0].security_id} ({resolution.candidates[0].legal_name}, "
            f"{resolution.candidates[0].class_designation})"
            if resolution.candidates
            else "no match"
        )
        context.say(f"{label:28} {ticker:5} -> {description}  [confidence: {resolution.confidence}]")

    current = master.resolve_ticker("FB")
    context.say(f"current FB resolves to: {current.candidates[0].security_id if current.candidates else 'none'} "
                f"({current.confidence})")
    conflicts = master.ticker_conflicts("FB")
    context.say(f"overlap conflicts stored for FB: {len(conflicts)} (ranges do not overlap, so none)")
    context.say("A ticker is time-bounded: the 2021 and 2024 answers are different securities with different ids.")

    context.results["identity"] = {
        "meta_security": meta_security,
        "reuse_security": reuse_security,
        "ticker_change": change,
        "current_fb": current.to_dict(),
        "conflicts": conflicts,
    }


# --------------------------------------------------------------------------- #
# D. Market data and corporate actions
# --------------------------------------------------------------------------- #
def _section_market_and_actions(context: DemoContext) -> None:
    context.section("D. Corporate actions: raw observations preserved, adjusted views derived")
    master = SecurityMaster(context.db)
    apple = master.require_issuer_by_cik(APPLE_CIK)
    securities = master.securities_for_issuer(apple["issuer_id"])
    if not securities:
        context.say("No AAPL security recorded; skipping market section.")
        return
    security_id = securities[0]["security_id"]

    source_id = SourceRegistry(context.db).ensure_custom(
        "Atlas synthetic market fixture",
        kind="synthetic",
        licence="Apache-2.0 (Atlas project)",
        redistribution="public_domain",
        notes="Deterministic synthetic prices around a 4-for-1 split; not real market data.",
    )
    calendar = TradingCalendar(context.db)
    calendar.ensure_venue("XNAS")
    csv_path = context.fixtures / "market" / "aapl_split_bars.csv"
    imported = import_csv_bars(
        csv_path, security_id=security_id, mic="XNAS", source_id=source_id, calendar=calendar
    )
    calendar.ensure_range("XNAS", imported.bars[0].session_date, imported.bars[-1].session_date)
    summary = BarStore(context.db).ingest(imported.bars)
    context.say(f"imported {len(imported.bars)} synthetic daily bars into {security_id} (XNAS); "
                f"inserted={summary.inserted} revisions={summary.revisions}")

    actions = ActionStore(context.db)
    split_id = actions.add(
        CorporateAction(
            security_id=security_id,
            action_type=ActionType.SPLIT.value,
            source_id=source_id,
            ex_date="2020-08-31",
            ratio_from=Decimal(1),
            ratio_to=Decimal(4),
            status="confirmed",
            notes="synthetic 4-for-1 split modelled on the real AAPL split of 2020-08-31",
        ),
        availability=availability_from_instant("2020-08-28T20:30:00Z", "demo.synthetic.action_announcement"),
    )
    dividend_id = actions.add(
        CorporateAction(
            security_id=security_id,
            action_type=ActionType.CASH_DIVIDEND.value,
            source_id=source_id,
            ex_date="2020-09-01",
            cash_amount=Decimal("0.205"),
            currency="USD",
            status="confirmed",
            notes="synthetic quarterly dividend used to test total-return mathematics",
        ),
        availability=availability_from_instant("2020-08-31T20:30:00Z", "demo.synthetic.action_announcement"),
    )
    context.say(f"actions recorded: {split_id} (4:1 split), {dividend_id} (0.205 USD dividend)")

    store = BarStore(context.db)
    raw = store.query(security_id, "XNAS", "2020-08-20", "2020-09-10")
    kept = actions.list(security_id)
    split_series = split_adjust(raw, kept)
    tr_series = total_return(raw, kept)
    index = dict(tr_series.total_return_index)

    context.say()
    context.say(f"{'session':12} {'raw close':>10} {'factor':>7} {'split-adj':>12} {'dividend':>9} {'TR index':>10}")
    raw_by_date = {bar.session_date: bar for bar in raw}
    for bar in split_series.bars:
        context.say(
            f"{bar.session_date:12} {raw_by_date[bar.session_date].close:>10} {bar.split_factor:>7} "
            f"{bar.close:>12.4f} {bar.dividend:>9} {index.get(bar.session_date, ''):>10}"
        )

    discrepancies = verify_split_continuity(raw, split_series)
    context.say()
    context.say(f"split continuity check: {'PASS' if not discrepancies else 'FAIL'} "
                f"({len(discrepancies)} discrepancies)")
    context.say("raw table unchanged after deriving views: "
                f"{'PASS' if all(bar.adjustment_status == 'raw' for bar in store.query(security_id, 'XNAS', '2020-08-20', '2020-09-10')) else 'FAIL'}")
    withheld = split_adjust(raw, kept, knowledge_as_of="2020-08-30")
    context.say(f"knowledge-filtered view (as of 2020-08-30) withholds {len(withheld.actions_withheld)} action(s): "
                "the split announced 2020-08-28 is applied, nothing later is.")

    context.results["market"] = {
        "security_id": security_id,
        "bars": len(raw),
        "split_action": split_id,
        "dividend_action": dividend_id,
        "adjustment_discrepancies": discrepancies,
        "total_return_index": dict(tr_series.total_return_index),
        "raw_snapshot": [bar.to_dict() for bar in raw],
    }


# --------------------------------------------------------------------------- #
# E. Financial X-Ray
# --------------------------------------------------------------------------- #
def _section_financial_xray(context: DemoContext) -> None:
    context.section("E. Financial X-Ray: value -> transformation -> source filing -> raw document")
    kernel = EvidenceKernel(context.db)
    apple = SecurityMaster(context.db).require_issuer_by_cik(APPLE_CIK)
    row = context.db.query_one(
        "SELECT evidence_id FROM evidence WHERE entity_id = ? AND concept = 'capex' "
        "ORDER BY period_end DESC LIMIT 1",
        (apple["issuer_id"],),
    )
    if row is None:
        context.say("No capital-expenditure evidence recorded; skipping.")
        return
    report = kernel.provenance(row["evidence_id"])
    for line in report.narrative:
        context.say("  " + line)
    if report.limitations:
        context.say("  limitations:")
        for limitation in report.limitations:
            context.say("    - " + limitation)
    context.say()
    context.say(f"derivation_kind: {report.record.derivation_kind}  rule: {report.record.derivation_rule}")
    context.results["xray"] = {
        "evidence_id": report.evidence_id,
        "concept": report.record.concept,
        "value": report.record.value_numeric,
        "unit": report.record.unit,
        "accession": report.record.accession_number,
        "raw_doc_id": report.record.raw_doc_id,
        "narrative": report.narrative,
        "limitations": report.limitations,
    }


# --------------------------------------------------------------------------- #
# F. Incremental synchronisation
# --------------------------------------------------------------------------- #
def _section_incremental(context: DemoContext) -> None:
    context.section("F. Incremental synchronisation: re-running ingestion must not duplicate")
    kernel = EvidenceKernel(context.db)
    before = kernel.count()
    report = _sync_fixture_company(context, context.fixtures / "sec", APPLE_CIK)
    after = kernel.count()
    evidence = report.evidence
    context.say(f"second sync: inserted={evidence['inserted']} duplicates={evidence['duplicates']} "
                f"superseding={evidence['superseding']}")
    context.say(f"evidence records before={before} after={after} -> "
                f"{'PASS' if before == after else 'FAIL'} (no duplication)")

    restatement_before = context.results.get("historical_reconstruction", {}).get("versions")
    _sync_fixture_company(context, context.fixtures / "sec_restatement", RESTATEMENT_CIK)
    issuer = SecurityMaster(context.db).require_issuer_by_cik(RESTATEMENT_CIK)
    versions_after = len([r for r in kernel.history(issuer["issuer_id"], "revenue") if r.unit == "USD"])
    context.say(f"restatement company versions before={restatement_before} after={versions_after} -> "
                f"{'PASS' if restatement_before == versions_after else 'FAIL'} (history preserved)")
    context.results["incremental"] = {
        "evidence_before": before,
        "evidence_after": after,
        "duplicates": evidence["duplicates"],
        "inserted": evidence["inserted"],
        "restatement_versions_before": restatement_before,
        "restatement_versions_after": versions_after,
    }


# --------------------------------------------------------------------------- #
# G. Evidence-first answer from a synthetic filing
# --------------------------------------------------------------------------- #
def _section_financial_answer(context: DemoContext) -> None:
    """Exercise the answer path the research interface uses, without a network call.

    The demonstration's Apple payload is XBRL facts, not a parsed statement: the answer engine
    reads statement tables out of ingested filings, so a certificate over the archived facts is
    impossible. Shipping the demo without this section meant a new user could install Atlas,
    run the demo and still have no certificate to look at. The filing ingested here is written
    by the project, invents a registrant and every figure in it, and says so on its face.
    """
    from .research.certificate import build_certificate
    from .research.certificate_verify import verify_payload
    from .research.financial_concepts import ConceptResolver, bind
    from .research.knowledge import KnowledgeEngine

    context.section("G. Evidence-first answer: a certificate over a synthetic filing")
    fixture = context.fixtures / "demo" / "atlas-demo-10k.html"
    if not fixture.is_file():
        context.say(f"fixture missing: {fixture} (section skipped)")
        context.results["financial_answer"] = {"status": "skipped", "reason": "fixture_missing"}
        return
    master = SecurityMaster(context.db)
    issuer_id = master.register_issuer(
        legal_name="Atlas Demonstration Industries, Inc. (synthetic)",
        cik=DEMO_ANSWER_CIK, entity_type="corporation",
    )
    engine = KnowledgeEngine(context.db)
    existing = context.db.query_one(
        "SELECT document_id FROM knowledge_document WHERE accession = ?",
        (DEMO_ANSWER_ACCESSION,),
    )
    if existing:
        document = engine.document(existing["document_id"])
    else:
        document = engine.ingest_document(
            issuer_id=issuer_id, accession=DEMO_ANSWER_ACCESSION, form_type="10-K",
            html=fixture.read_bytes(), filed_date="2024-02-15",
            acceptance_time="2024-02-15T21:30:00Z", period_of_report="2023-12-31",
            rights="project_authored",
            copyright_holder="Atlas project (demonstration fixture)",
            copyright_licence="written for the Atlas demonstration; distributed as part of the "
                              "Atlas source distribution, with no separate licence granted",
            primary_document_url="fixture://demo/atlas-demo-10k.html",
        )
    context.say("issuer     : Atlas Demonstration Industries, Inc. (synthetic registrant,")
    context.say("             no CIK, no securities, every figure invented)")
    context.say(f"document   : {document['document_id']}  10-K filed 2024-02-15  "
                f"tables={document['table_count']} units={document['unit_count']}  "
                f"availability={document['availability_precision']}")
    cutoff = iso(utcnow())
    resolver = ConceptResolver(engine)
    context.say(f"question   : what was gross profit in fiscal {DEMO_ANSWER_PERIOD}?")
    resolution = resolver.resolve(issuer_id, DEMO_ANSWER_CONCEPT, DEMO_ANSWER_PERIOD, cutoff)
    if resolution.status != "resolved" or resolution.cell is None:
        context.say(f"answer     : refused ({resolution.reason or resolution.status})")
        context.results["financial_answer"] = {
            "status": "refused", "reason": resolution.reason or resolution.status}
        return
    binding = bind(resolution, issuer_id, DEMO_ANSWER_CONCEPT)
    if binding is None:
        context.say("answer     : resolved cell could not be bound")
        context.results["financial_answer"] = {"status": "binding_failed"}
        return
    answer = resolver.answers.lookup_bound(binding, cutoff)
    context.say(f"answer     : {answer.get('display') or answer.get('value')} {binding.currency} "
                f"({binding.row_label}, {binding.period}, {binding.statement_title})")
    context.say(f"outcome    : {answer.get('outcome')}  verification={answer.get('verification')}")
    context.say(f"source     : {binding.accession} {binding.statement_family} "
                f"table {binding.table_id} cell {binding.cell_id} row {binding.row} "
                f"column {binding.column}")
    document_row = context.db.query_one(
        "SELECT sha256 FROM knowledge_document WHERE document_id = ?",
        (binding.document_id,),
    )
    certificate = build_certificate(
        research_question=f"What was gross profit in fiscal {DEMO_ANSWER_PERIOD}?",
        answer=answer,
        bindings=[binding],
        cutoff=cutoff,
        issuer_identity={"cik": None, "issuer_name":
                         "Atlas Demonstration Industries, Inc. (synthetic)",
                         "schema": "atlas.mcp.issuer.v1"},
        source_documents={binding.document_id: {
            "sha256": document_row["sha256"] if document_row else None,
            "primary_document_url": "fixture://demo/atlas-demo-10k.html",
            "form_type": "10-K",
        }},
    )
    report = verify_payload(certificate)
    context.say(f"certificate: {certificate['certificate_fingerprint'][:16]}...  "
                f"level={report.get('level')}")
    context.say("semantics  : the cell is verified against its source table and the arithmetic")
    context.say("             is checked; the economic interpretation is the analyst's job.")
    context.results["financial_answer"] = {
        "status": "answered",
        "issuer_id": issuer_id,
        "document_id": document["document_id"],
        "concept": DEMO_ANSWER_CONCEPT,
        "period": DEMO_ANSWER_PERIOD,
        "value": str(binding.value),
        "verification": report.get("level"),
        "answer_outcome": answer.get("outcome"),
        "certificate_fingerprint": certificate["certificate_fingerprint"],
        "accession": binding.accession,
    }


# --------------------------------------------------------------------------- #
# H. Validation and statistics
# --------------------------------------------------------------------------- #
def _section_validation(context: DemoContext) -> None:
    context.section("H. Dataset integrity and statistics")
    report = run_validation(context.db)
    context.say(f"validation: {len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    for finding in report.findings[:12]:
        context.say(f"  [{finding.severity}] {finding.code}: {finding.detail}")
    stats = summarize(context.db)
    context.say()
    context.say("stored rows:")
    for table, count in stats["tables"].items():
        if count:
            context.say(f"  {table:22} {count}")
    context.say(f"integrity_check: {stats['integrity_check']}")
    context.say(f"data-quality issues by severity: {issue_summary(context.db)}")
    context.results["validation"] = {
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "findings": [f.to_dict() for f in report.findings],
        "stats": stats,
    }
