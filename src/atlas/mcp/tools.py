"""The Atlas MCP tool surface.

Each tool is a bounded adapter over an existing Atlas service: the temporal evidence
kernel, the Financial Knowledge Engine, the concept resolver, the FEC runtime, the
valuation service and the research object store. No tool accepts SQL, a shell command, a
filesystem path or a URL, and no tool computes a financial value itself — so the MCP
surface cannot report a number the browser would not also report.

Every response carries the identifiers, availability semantics and units the underlying
service already produces. A tool that would have to invent a value refuses instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..core.errors import AtlasError
from ..core.temporal import iso, utcnow
from ..fec import compile_model
from ..fec.operators import REGISTRY
from ..fec.runtime import ExecutionEngine
from ..fec import valuation as fec_valuation
from ..research import objects as research_objects
from ..research.certificate_verify import verify_payload
from ..research.filing_evidence import cutoff_instant
from ..research.financial_concepts import CONCEPTS, ConceptResolver, bind
from ..research.knowledge import KnowledgeEngine
from ..storage.db import Database
from ..terminal import read_models

#: A response larger than this is a bug or an attempt at resource exhaustion, not an answer.
MAX_RESULT_BYTES = 1_000_000
#: Documents (certificates, research artifacts, model specs) accepted from the caller.
MAX_DOCUMENT_BYTES = 512_000

SCHEMA_PREFIX = "atlas.mcp"


class ToolError(Exception):
    """A tool failed for a reason the caller can act on."""

    def __init__(self, code: str, message: str, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})

    def as_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "context": self.context}}


@dataclass(frozen=True, slots=True)
class ToolContext:
    db_path: str
    allow_mutations: bool = False
    #: Operator-configured columnar dataset root. Never accepted from a tool argument:
    #: no MCP tool may read an arbitrary filesystem path.
    columnar_root: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]
    mutating: bool = False


# ------------------------------------------------------------------------ helpers

def _open(context: ToolContext) -> Database:
    try:
        return Database(context.db_path, create=False)
    except AtlasError as exc:
        raise ToolError("database_unavailable", str(exc), {"path": context.db_path}) from exc


def _document(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ToolError("invalid_document", f"{name} must be a JSON object")
    size = len(json.dumps(value, default=str).encode("utf-8"))
    if size > MAX_DOCUMENT_BYTES:
        raise ToolError("document_too_large", f"{name} exceeds {MAX_DOCUMENT_BYTES} bytes",
                        {"bytes": size})
    return value


def _bound(payload: dict[str, Any]) -> dict[str, Any]:
    size = len(json.dumps(payload, default=str).encode("utf-8"))
    if size > MAX_RESULT_BYTES:
        raise ToolError(
            "result_too_large",
            "the result exceeds the MCP response bound; ask a narrower question",
            {"bytes": size, "limit": MAX_RESULT_BYTES},
        )
    return payload


def _cutoff(as_of: str | None) -> str:
    if not as_of:
        return iso(utcnow())
    resolved = cutoff_instant(as_of)
    if resolved is None:  # pragma: no cover - cutoff_instant returns a value for any date
        raise ToolError("invalid_cutoff", "as_of could not be interpreted as a date")
    return resolved


def _availability(record: Mapping[str, Any]) -> dict[str, Any]:
    """Describe availability without ever upgrading an estimate to a verified instant."""
    precision = record.get("availability_precision")
    verified = precision in {"exact", "date"}
    return {
        "availability_time": record.get("availability_time"),
        "availability_precision": precision,
        "availability_basis": record.get("availability_basis"),
        "is_estimated": not verified,
        "note": (
            "availability_time is an observation with the stated precision"
            if verified else
            "availability_time is a modelled upper bound, not an observed public-release "
            "instant; it may order and exclude evidence but must never be reported as "
            "verified historical availability"
        ),
    }


# ------------------------------------------------------------------------- tools

def search_companies(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    db = _open(context)
    try:
        items = read_models.list_companies(db, q=arguments.get("q"),
                                           limit=int(arguments.get("limit", 10)))
    finally:
        db.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.company_search.v1",
        "query": arguments.get("q"),
        "count": len(items),
        "items": items,
        "policy": "only issuers present in this Atlas database are returned; nothing is invented",
    })


def _columnar(context: ToolContext):
    """Open the operator's columnar build, or explain why the tools are unavailable."""
    if not context.columnar_root:
        raise ToolError(
            "columnar_unavailable",
            "no columnar dataset is configured for this server; start `atlas mcp "
            "--columnar-root <dir>` to expose the full-universe index",
        )
    from ..open_data.columnar import ColumnarEvidence

    return ColumnarEvidence(context.columnar_root)


def search_columnar_companies(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    evidence = _columnar(context)
    try:
        items = evidence.search_companies(str(arguments["q"]),
                                          limit=int(arguments.get("limit", 10)))
    finally:
        evidence.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.columnar_company_search.v1",
        "query": arguments["q"],
        "count": len(items),
        "items": items,
        "policy": "issuers present in the configured columnar build only",
    })


def query_columnar_evidence(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Point-in-time facts for one issuer, selected the way the evidence kernel selects."""
    evidence = _columnar(context)
    try:
        statement = evidence.statement(str(arguments["cik"]), as_of=arguments.get("as_of"))
        availability = evidence.availability(str(arguments["cik"]))
    finally:
        evidence.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.columnar_evidence.v1",
        "cik": statement["cik"],
        "period_end": statement["period_end"],
        "as_of": arguments.get("as_of"),
        "concepts": statement["concepts"],
        "evidence": statement["evidence"],
        "contradictions": statement["contradictions"],
        "availability": availability,
        "selection_policy": statement["selection_policy"],
        "scope": statement["scope"],
        "notes": [
            "historical reads exclude observations whose public availability is unknown or "
            "only modelled; `availability` reports how many were excluded",
            "values are exact decimals; no currency conversion is applied or implied",
        ],
    })


def screen_columnar(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Rank comparable issuers; an incomparable request is refused with its reason."""
    from ..open_data.columnar import IncomparableScreen, ScreenSpec

    evidence = _columnar(context)
    try:
        spec = ScreenSpec(
            concept=str(arguments["concept"]),
            fiscal_year=arguments.get("fiscal_year"),
            period=str(arguments.get("period", "auto")),
            currency=arguments.get("currency"),
            unit=arguments.get("unit"),
            as_of=arguments.get("as_of"),
        )
        try:
            report = evidence.screen_report(spec, minimum=arguments.get("minimum"),
                                            limit=int(arguments.get("limit", 50)))
        except IncomparableScreen as exc:
            raise ToolError("incomparable_screen", str(exc), {"groups": exc.groups}) from exc
    finally:
        evidence.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.columnar_screen.v1",
        "request": report["request"],
        "comparable": report["comparable"],
        "selected": report["selected"],
        "ranked_total": report.get("ranked_total"),
        "refused": report["refused"],
        "excluded": report["excluded"],
        "notes": report.get("notes") or [],
    })


def get_company_financials(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    db = _open(context)
    try:
        payload = read_models.statements(
            db,
            arguments["identifier"],
            statement=arguments.get("statement", "income"),
            period=arguments.get("period", "FY"),
            as_of=arguments.get("as_of"),
            mode=arguments.get("mode", "public_available"),
            limit=int(arguments.get("limit", 4)),
        )
    finally:
        db.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.company_financials.v1",
        "statement": payload,
        "provenance": {
            "policy": "each cell carries an evidence_id, availability time and precision; "
                      "excluded_unknown_availability counts facts Atlas refused to place",
            "magnitudes_as_reported": True,
        },
    })


def search_filings(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    db = _open(context)
    try:
        engine = KnowledgeEngine(db)
        query = arguments.get("query")
        if query:
            payload = engine.search(
                query,
                issuer_id=arguments.get("issuer_id"),
                cutoff=arguments.get("as_of"),
                policy=arguments.get("policy", "public_available"),
                limit=int(arguments.get("limit", 8)),
            )
            return _bound({"schema": f"{SCHEMA_PREFIX}.filing_search.v1", "search": payload})
        items = engine.list_documents(issuer_id=arguments.get("issuer_id"),
                                      limit=int(arguments.get("limit", 20)))
        return _bound({
            "schema": f"{SCHEMA_PREFIX}.filing_search.v1",
            "documents": items,
            "count": len(items),
            "policy": "archived documents only; a filing with no archived text reports no passage",
        })
    finally:
        db.close()


def get_evidence(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    db = _open(context)
    try:
        payload = read_models.xray(db, arguments["evidence_id"])
    finally:
        db.close()
    return _bound({"schema": f"{SCHEMA_PREFIX}.evidence.v1", "evidence": payload})


def resolve_financial_question(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    db = _open(context)
    try:
        engine = KnowledgeEngine(db)
        resolver = ConceptResolver(engine)
        cutoff = _cutoff(arguments.get("as_of"))
        resolution = resolver.resolve(
            arguments["issuer_id"],
            arguments["concept"],
            arguments["period"],
            cutoff,
            context=arguments.get("scope", "consolidated"),
        )
        header = {
            "schema": f"{SCHEMA_PREFIX}.financial_answer.v1",
            "question": {
                "issuer_id": arguments["issuer_id"],
                "concept": arguments["concept"],
                "period": arguments["period"],
                "as_of": cutoff,
                "scope": arguments.get("scope", "consolidated"),
            },
            "resolution": resolution.as_dict(),
        }
        if resolution.status != "resolved" or resolution.cell is None:
            return _bound({
                **header,
                "answered": False,
                "refused": True,
                "refusal": {
                    "reason": resolution.reason or resolution.status,
                    "candidates": resolution.candidates[:5],
                    "explanation": (
                        "Atlas refused rather than approximate: the concept did not resolve to "
                        "exactly one verified consolidated cell for that period at that cutoff."
                    ),
                },
            })
        binding = bind(resolution, arguments["issuer_id"], arguments["concept"])
        if binding is None:  # pragma: no cover - bind() mirrors the resolved status
            raise ToolError("binding_failed", "the resolved cell could not be bound")
        answer = resolver.answers.lookup_bound(binding, cutoff)
        return _bound({
            **header,
            "answered": answer.get("outcome") == "answered",
            "refused": answer.get("outcome") != "answered",
            "answer": answer,
            "evidence": {
                "document_id": binding.document_id,
                "accession": binding.accession,
                "table_id": binding.table_id,
                "unit_id": binding.unit_id,
                "cell_id": binding.cell_id,
                "row": binding.row,
                "column": binding.column,
                "row_label": binding.row_label,
                "column_label": binding.column_label,
                "currency": binding.currency,
                "scale": binding.scale,
                "period": binding.period,
                "rights": binding.rights,
            },
            "availability": _availability({
                "availability_time": binding.availability_time,
                "availability_precision": binding.availability_precision,
            }),
            "semantics": {
                "verified_but_not_proven_correct": True,
                "note": "the cell was verified against its source table; economic intent is the "
                        "analyst's judgement and is not certified by this tool",
            },
        })
    finally:
        db.close()


def verify_financial_answer(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    certificate = _document(arguments["certificate"], "certificate")
    report = verify_payload(certificate)
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.certificate_verification.v1",
        "report": report,
        "note": "verification proves internal consistency and, with pinned source bytes, source "
                "identity; it does not prove the economic interpretation is correct",
    })


def compare_companies(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    statement = arguments.get("statement", "income")
    period = arguments.get("period", "FY")
    db = _open(context)
    try:
        left = read_models.statements(db, arguments["left"], statement=statement, period=period,
                                      as_of=arguments.get("as_of"),
                                      mode=arguments.get("mode", "public_available"),
                                      limit=int(arguments.get("limit", 3)))
        right = read_models.statements(db, arguments["right"], statement=statement, period=period,
                                       as_of=arguments.get("as_of"),
                                       mode=arguments.get("mode", "public_available"),
                                       limit=int(arguments.get("limit", 3)))
    finally:
        db.close()
    return _bound(_comparison(left, right))


def _comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_periods = [column["period_end"] for column in left["columns"]]
    right_periods = [column["period_end"] for column in right["columns"]]
    shared_periods = [value for value in left_periods if value in set(right_periods)]
    if not shared_periods:
        raise ToolError(
            "incompatible_periods",
            "the two companies share no reporting period for this statement",
            {"left": left_periods, "right": right_periods},
        )
    left_rows = {row["concept"]: row for row in left["rows"]}
    right_rows = {row["concept"]: row for row in right["rows"]}
    shared_concepts = [key for key in left_rows if key in right_rows]
    if not shared_concepts:
        raise ToolError(
            "incompatible_definitions",
            "the two statements share no row definition; refusing to compare unlike concepts",
            {"left": sorted(left_rows), "right": sorted(right_rows)},
        )
    excluded: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for concept in shared_concepts:
        lrow, rrow = left_rows[concept], right_rows[concept]
        if lrow["unit"] != rrow["unit"]:
            excluded.append({"concept": concept, "reason": "unit_mismatch",
                             "left_unit": lrow["unit"], "right_unit": rrow["unit"]})
            continue
        left_cells = {left["columns"][index]["period_end"]: cell
                      for index, cell in enumerate(lrow["cells"])}
        right_cells = {right["columns"][index]["period_end"]: cell
                       for index, cell in enumerate(rrow["cells"])}
        for period_end in shared_periods:
            lcell = left_cells.get(period_end, {})
            rcell = right_cells.get(period_end, {})
            if lcell.get("missing") or rcell.get("missing"):
                excluded.append({"concept": concept, "period": period_end,
                                 "reason": "value_missing"})
                continue
            delta = None
            if lcell.get("value") is not None and rcell.get("value") is not None:
                delta = lcell["value"] - rcell["value"]
            comparisons.append({
                "concept": concept,
                "label": lrow.get("label"),
                "period_end": period_end,
                "unit": lrow["unit"],
                "left": {"issuer_id": left["issuer"]["issuer_id"], "value": lcell.get("value"),
                         "evidence_id": lcell.get("evidence_id")},
                "right": {"issuer_id": right["issuer"]["issuer_id"], "value": rcell.get("value"),
                          "evidence_id": rcell.get("evidence_id")},
                "absolute_difference_magnitudes": delta,
            })
    if not comparisons:
        raise ToolError(
            "incompatible_operands",
            "no comparable cell survived the period, unit and definition checks",
            {"excluded": excluded},
        )
    return {
        "schema": f"{SCHEMA_PREFIX}.company_comparison.v1",
        "statement": left.get("statement"),
        "period": left.get("period"),
        "as_of": left.get("as_of"),
        "mode": left.get("mode"),
        "compatibility": {
            "shared_periods": shared_periods,
            "shared_concepts": shared_concepts,
            "excluded": excluded,
            "rule": "compare only identical row definitions, identical units and identical "
                    "period ends; refuse rather than align unlike figures",
        },
        "rows": comparisons,
        "note": "differences are between reported magnitudes. They are not per-share, not "
                "currency-converted and not adjusted for accounting-policy differences.",
    }


def inspect_model(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    key = arguments.get("model")
    items = [
        {"key": name, "version": spec.version, "arity": spec.arity,
         "formula": spec.formula, "description": spec.description}
        for name, spec in sorted(REGISTRY.items())
    ]
    if key is not None:
        items = [item for item in items if item["key"] == key]
        if not items:
            raise ToolError("unknown_model", f"no registered operator named {key!r}",
                            {"supported": sorted(REGISTRY)})
    return {
        "schema": f"{SCHEMA_PREFIX}.model_catalog.v1",
        "items": items,
        "expression_policy": "allowlisted AST arithmetic and named functions; no eval/exec",
    }


def run_supported_model(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    spec = _document(arguments["spec"], "spec")
    inputs = _document(arguments.get("inputs", {}), "inputs")
    persist = bool(arguments.get("persist", False))
    if persist and not context.allow_mutations:
        raise ToolError(
            "authorization_required",
            "persisting a model run is a mutation; restart the server with --allow-mutations",
        )
    model = compile_model(spec)
    db = _open(context)
    try:
        result = ExecutionEngine(db).execute(model, inputs, persist=persist)
    finally:
        db.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.model_run.v1",
        "run": result,
        "compiled": model.to_dict(),
        "persisted": persist,
    })


def run_scenario(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    assumptions = _document(arguments.get("assumptions", {}), "assumptions")
    db = _open(context)
    try:
        payload = fec_valuation.scenarios(
            db,
            arguments["identifier"],
            assumptions,
            as_of=arguments.get("as_of"),
            mode=arguments.get("mode", "public_available"),
        )
    finally:
        db.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.scenario_analysis.v1",
        "scenarios": payload,
        "note": "scenario outputs are model-conditional; they are not forecasts and carry no "
                "probability. Assumption changes are reported with every result.",
    })


def get_research_workspace(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    db = _open(context)
    try:
        stored = research_objects.ResearchObjectStore(db).get(arguments["object_id"])
    finally:
        db.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.research_object.v1",
        "object": stored,
        "policy": "returned as stored; revisions are separate objects and are never merged",
    })


def verify_research_artifact(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    document = dict(_document(arguments["artifact"], "artifact"))
    # A stored research object carries its content hash beside the document. Accept it there
    # or as an explicit argument, then remove it: the document schema refuses unknown fields,
    # and silently tolerating one here would weaken the same check on the write path.
    declared = arguments.get("content_hash") or document.pop("content_hash", None)
    validated = research_objects.validate_document(document)
    computed = research_objects.content_hash(validated)
    evidence_ids = list(document.get("evidence_ids") or [])
    db = _open(context)
    try:
        missing: list[str] = []
        if evidence_ids:
            marks = ",".join("?" for _ in evidence_ids)
            found = {row["evidence_id"] for row in db.query(
                f"SELECT evidence_id FROM evidence WHERE evidence_id IN ({marks})", evidence_ids)}
            missing = [item for item in evidence_ids if item not in found]
    finally:
        db.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.research_artifact_verification.v1",
        "verified": declared is None or declared == computed,
        "declared_content_hash": declared,
        "computed_content_hash": computed,
        "cites_unknown_evidence": missing,
        "note": "content_hash covers canonical content only. It proves the document was not "
                "altered after hashing; it does not establish that its claims are true.",
    })


def inspect_data_health(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    db = _open(context)
    try:
        counts = {
            table: int(db.scalar(f"SELECT COUNT(*) FROM {table}", default=0) or 0)
            for table in ("evidence", "issuer", "security", "bar", "knowledge_document",
                          "knowledge_unit", "knowledge_table", "research_object",
                          "economic_observation")
            if db.scalar(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table,),
                default=0,
            )
        }
        payload = {
            "schema": f"{SCHEMA_PREFIX}.data_health.v1",
            "database": str(db.path),
            "schema_version": db.schema_version(),
            "integrity_check": db.integrity_check(),
            "counts": counts,
            "policy": "counts describe this local database only; no coverage claim is implied",
        }
    finally:
        db.close()
    return _bound(payload)


def save_research_object(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if not context.allow_mutations:
        raise ToolError(
            "authorization_required",
            "writing a research object is a persistent mutation; restart the server with "
            "--allow-mutations to authorise it",
        )
    document = _document(arguments["document"], "document")
    db = _open(context)
    try:
        stored = research_objects.ResearchObjectStore(db).create(
            document, owner_id=arguments.get("owner_id", "local")
        )
    finally:
        db.close()
    return _bound({
        "schema": f"{SCHEMA_PREFIX}.research_object_saved.v1",
        "object_id": stored["object_id"],
        "content_hash": stored["content_hash"],
    })


def _object(properties: Mapping[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required or []),
        "additionalProperties": False,
    }


_LIMIT = {"type": "integer", "minimum": 1, "maximum": 50}
_AS_OF = {"type": "string", "minLength": 8, "maxLength": 40,
          "pattern": r"^\d{4}-\d{2}-\d{2}"}
_MODE = {"type": "string", "enum": ["public_available", "atlas_ingested"]}
_STATEMENT = {"type": "string", "enum": ["income", "balance", "cashflow"]}
_PERIOD = {"type": "string", "enum": ["FY", "Q"]}

TOOLS: dict[str, ToolSpec] = {
    "search_companies": ToolSpec(
        "search_companies", "Search companies",
        "Find issuers in this Atlas database by ticker, name or CIK. Unknown symbols return an "
        "empty list: Atlas does not invent a security.",
        _object({"q": {"type": "string", "minLength": 1, "maxLength": 120}, "limit": _LIMIT}),
        search_companies,
    ),
    "search_columnar_companies": ToolSpec(
        "search_columnar_companies", "Search the full-universe index",
        "Find issuers in the configured columnar build (the full SEC company universe) by "
        "name. This index answers without importing it into SQLite.",
        _object({"q": {"type": "string", "minLength": 1, "maxLength": 120},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
        search_columnar_companies,
    ),
    "query_columnar_evidence": ToolSpec(
        "query_columnar_evidence", "Query columnar evidence",
        "Point-in-time facts for one issuer from the columnar index, with the same "
        "availability and adjudication semantics as the evidence kernel: unknown or "
        "modelled availability is excluded from a historical cut-off and counted.",
        _object({"cik": {"type": "string", "minLength": 1, "maxLength": 20},
                 "as_of": _AS_OF}, ["cik"]),
        query_columnar_evidence,
    ),
    "screen_columnar": ToolSpec(
        "screen_columnar", "Screen the full universe",
        "Rank issuers on one concept and fiscal year. Mixed currencies, units, durations or "
        "scopes are refused rather than ranked; every refusal is returned with its reason.",
        _object({"concept": {"type": "string", "minLength": 1, "maxLength": 80},
                 "fiscal_year": {"type": "integer", "minimum": 1990, "maximum": 2100},
                 "period": {"type": "string", "enum": ["auto", "annual", "quarter", "instant"]},
                 "currency": {"type": "string", "minLength": 3, "maxLength": 3},
                 "unit": {"type": "string", "minLength": 1, "maxLength": 24},
                 "as_of": _AS_OF, "minimum": {"type": "number"},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 200}},
                ["concept"]),
        screen_columnar,
    ),
    "get_company_financials": ToolSpec(
        "get_company_financials", "Get company financial statements",
        "Point-in-time income, balance or cash-flow statements. Every cell carries an evidence "
        "id, availability time and precision; facts whose availability is unknown are excluded.",
        _object({"identifier": {"type": "string", "minLength": 1, "maxLength": 120},
                 "statement": _STATEMENT, "period": _PERIOD, "as_of": _AS_OF, "mode": _MODE,
                 "limit": {"type": "integer", "minimum": 1, "maximum": 12}},
                ["identifier"]),
        get_company_financials,
    ),
    "search_filings": ToolSpec(
        "search_filings", "Search archived filings",
        "List archived SEC filings for an issuer, or retrieve passages for a query with the "
        "active information cutoff. A filing without archived text returns no excerpt.",
        _object({"issuer_id": {"type": "string", "minLength": 1, "maxLength": 80},
                 "query": {"type": "string", "minLength": 2, "maxLength": 400},
                 "as_of": _AS_OF,
                 "policy": {"type": "string", "enum": ["public_available", "atlas_ingested"]},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 30}}),
        search_filings,
    ),
    "get_evidence": ToolSpec(
        "get_evidence", "Inspect one evidence record",
        "Full provenance for one immutable observation: source document, filing context, "
        "availability precision and revision chain.",
        _object({"evidence_id": {"type": "string", "minLength": 3, "maxLength": 120}},
                ["evidence_id"]),
        get_evidence,
    ),
    "resolve_financial_question": ToolSpec(
        "resolve_financial_question", "Resolve a financial question",
        "Map a registered concept and period to exactly one verified consolidated cell and "
        "return the answer with its evidence, units, scale and availability. Ambiguity is "
        "refused, never approximated.",
        _object({"issuer_id": {"type": "string", "minLength": 3, "maxLength": 80},
                 "concept": {"type": "string", "enum": sorted(CONCEPTS)},
                 "period": {"type": "string", "minLength": 4, "maxLength": 20},
                 "as_of": _AS_OF,
                 "scope": {"type": "string", "enum": ["consolidated", "any"]}},
                ["issuer_id", "concept", "period"]),
        resolve_financial_question,
    ),
    "verify_financial_answer": ToolSpec(
        "verify_financial_answer", "Verify an answer certificate",
        "Independently verify an Atlas research certificate: identity, availability, types, "
        "arithmetic and fingerprints. Returns the verification level and every diagnostic.",
        _object({"certificate": {"type": "object"}}, ["certificate"]),
        verify_financial_answer,
    ),
    "compare_companies": ToolSpec(
        "compare_companies", "Compare two companies",
        "Compare one statement across two issuers, enforcing identical row definitions, units "
        "and period ends. Incompatible operands are refused with the reason.",
        _object({"left": {"type": "string", "minLength": 1, "maxLength": 120},
                 "right": {"type": "string", "minLength": 1, "maxLength": 120},
                 "statement": _STATEMENT, "period": _PERIOD, "as_of": _AS_OF, "mode": _MODE,
                 "limit": {"type": "integer", "minimum": 1, "maximum": 8}},
                ["left", "right"]),
        compare_companies,
    ),
    "inspect_model": ToolSpec(
        "inspect_model", "Inspect registered models",
        "List the allowlisted FEC operators with their versions, arity and formula, or inspect "
        "one by key.",
        _object({"model": {"type": "string", "minLength": 1, "maxLength": 80}}),
        inspect_model,
    ),
    "run_supported_model": ToolSpec(
        "run_supported_model", "Run a supported model",
        "Compile and execute an atlas.model.v1 specification against typed inputs. Persisting a "
        "run is a mutation and requires explicit server authorization.",
        _object({"spec": {"type": "object"}, "inputs": {"type": "object"},
                 "persist": {"type": "boolean"}}, ["spec"]),
        run_supported_model,
    ),
    "run_scenario": ToolSpec(
        "run_scenario", "Run valuation scenarios",
        "Run the DCF scenario set (base, bull, bear or caller-supplied overrides) for an issuer "
        "and return each value with the assumptions that produced it.",
        _object({"identifier": {"type": "string", "minLength": 1, "maxLength": 120},
                 "assumptions": {"type": "object"}, "as_of": _AS_OF, "mode": _MODE},
                ["identifier"]),
        run_scenario,
    ),
    "get_research_workspace": ToolSpec(
        "get_research_workspace", "Read a saved research object",
        "Return one stored research object exactly as saved, with its content hash and version.",
        _object({"object_id": {"type": "string", "minLength": 3, "maxLength": 120}},
                ["object_id"]),
        get_research_workspace,
    ),
    "verify_research_artifact": ToolSpec(
        "verify_research_artifact", "Verify a research artifact",
        "Recompute an artifact's canonical content hash, validate its structure and check that "
        "every cited evidence id exists in this database.",
        _object({"artifact": {"type": "object"},
                 "content_hash": {"type": "string", "minLength": 64, "maxLength": 64}},
                ["artifact"]),
        verify_research_artifact,
    ),
    "inspect_data_health": ToolSpec(
        "inspect_data_health", "Inspect data health",
        "Report schema version, SQLite integrity and row counts for this local database.",
        _object({}),
        inspect_data_health,
    ),
    "save_research_object": ToolSpec(
        "save_research_object", "Save a research object",
        "Persist a versioned research object. This is the only mutating tool and it refuses "
        "unless the server was started with --allow-mutations.",
        _object({"document": {"type": "object"},
                 "owner_id": {"type": "string", "minLength": 1, "maxLength": 60}},
                ["document"]),
        save_research_object,
        mutating=True,
    ),
}


__all__ = [
    "MAX_DOCUMENT_BYTES",
    "MAX_RESULT_BYTES",
    "TOOLS",
    "ToolContext",
    "ToolError",
    "ToolSpec",
]
