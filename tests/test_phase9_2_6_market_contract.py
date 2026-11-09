"""Phase 9.2.6: one market-evidence contract, many consumers.

These tests do not check that fields exist. They check that independent public paths —
the price summary, the Markets read model, the issuer metrics and the equity service —
resolve the *same immutable observation* for the same security, date and policy, and that
they stay consistent when a provider is corrected, filtered, pinned or missing.

The failure this suite exists for is duplication: before this change, "latest price" was
answered by three different queries. A test here that passes for one path and fails for
another is a real semantic divergence, not a formatting difference.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from atlas.applications.rights import DataRightsEngine
from atlas.entities.master import SecurityMaster
from atlas.fec import compatibility
from atlas.fec.compiler import COMPILER_VERSION
from atlas.fec.operators import REGISTRY, operator_versions
from atlas.market import evidence
from atlas.research import prices, rights as data_rights
from atlas.terminal import read_models
from atlas.terminal.exposure import ACK_ENV, assess_bind

DAY = "2025-01-02"
EARLIER = "2024-12-31"


def _identity(db, *, ticker: str = "TST", mic: str = "XNYS"):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Test Bank", cik="1000001", sic="6021")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, mic, valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(
        listing, ticker, valid_from="2020-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    return master, issuer, security, listing


def _row(close: float, *, day: str = DAY):
    return {
        "date": day, "open": close - 0.5, "high": close + 0.5,
        "low": close - 1.0, "close": close, "volume": 1000,
    }


def _import(
    db, *, close: float, source: str = "Provider A", licence: str = "Vendor terms",
    redistribution: str = "restricted", day: str = DAY, mic: str | None = None, **kwargs,
):
    return prices.import_price_series(
        db, ticker=kwargs.pop("ticker", "TST"), rows=[_row(close, day=day)],
        source_name=source, licence=licence, redistribution=redistribution,
        adjustment_semantics="unadjusted", mic=mic, **kwargs,
    )


def _security_dict(db, security_id):
    return dict(db.query_one("SELECT * FROM security WHERE security_id = ?", (security_id,)))


def _selection(db, security_id, *, date_text=DAY, **kwargs) -> evidence.PriceSelection:
    return evidence.select_price(db, security_id, date_text, **kwargs)


# --------------------------------------------------------------------- contract
def test_observation_preserves_decimal_precision_and_identity(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.05)

    selection = _selection(db, security)
    observation = selection.observation
    assert isinstance(observation, evidence.MarketObservation)
    assert observation.close == Decimal("10.05")
    assert observation.close_decimal_text == "10.05"
    # The canonical text — not the JSON number — is what the content hash covers.
    assert observation.to_dict()["content_hash"] == observation.content_hash
    assert observation.to_pin()["observation_id"] == observation.observation_id
    assert "close" not in observation.to_pin()
    assert observation.rights_class == "restricted"
    assert observation.export_allowed is False


def test_contract_is_immutable(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    selection = _selection(db, security)
    with pytest.raises(Exception):
        selection.observation.close = Decimal("1")  # type: ignore[misc]
    with pytest.raises(Exception):
        selection.policy = "latest_revision"  # type: ignore[misc]


def test_selection_states_its_policy_version_and_basis(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    selection = _selection(db, security)
    assert selection.policy == prices.SOURCE_SELECTION_POLICY
    assert selection.requested_policy == "latest_session"
    assert selection.information_cutoff == DAY
    assert selection.rationale
    assert selection.missing_status is None
    legacy = selection.to_legacy()
    assert legacy["observation_id"] == selection.observation.observation_id
    assert legacy["dimensions"]["provider"] == "single_provider_selected_then_held_constant"


def test_missing_observation_is_explicit_and_never_substituted(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0, day=DAY)
    selection = _selection(db, security, date_text=EARLIER)
    assert selection.observation is None
    assert selection.missing_status == evidence.MISSING_NO_OBSERVATION
    assert selection.exact_replay_eligible is False
    assert prices.price_on_or_before(db, security, EARLIER) is None
    history = prices.price_history(db, security, end_date=EARLIER)
    assert history["status"] == "unavailable" and history["points"] == []


def test_comparison_rejects_a_price_after_the_cutoff(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0, day=DAY)
    selection = _selection(db, security, date_text="2999-12-31")
    comparison = evidence.compare_model_to_market(
        selection=selection, value_per_share=12.0,
        accounting_period_end="2024-09-30", information_cutoff="2024-12-31",
    )
    assert comparison.status == "rejected_lookahead"
    assert comparison.lookahead_safe is False
    assert comparison.price_close == Decimal("10.0")


def test_comparison_records_a_mixed_date_gap(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0, day=DAY)
    comparison = evidence.compare_model_to_market(
        selection=_selection(db, security),
        value_per_share=12.0,
        accounting_period_end="2024-09-30",
        information_cutoff="2999-12-31",
        model_version="equity-dcf.v2",
    )
    assert comparison.status == "available"
    assert comparison.mixed_date is True
    assert comparison.date_gap_days > 0
    assert any("mixed-date" in note for note in comparison.uncertainty)
    assert comparison.model_version == "equity-dcf.v2"


# ------------------------------------------------------ cross-consumer agreement
def test_two_providers_same_session_resolve_to_one_deterministic_choice(db):
    master, _, security, _ = _identity(db)
    first = _import(db, close=10.0, source="Provider A")
    second = _import(db, close=12.0, source="Provider B")
    selection = _selection(db, security)

    expected = min(first["source"]["source_id"], second["source"]["source_id"])
    assert selection.selected_source_id == expected
    # The rejected provider is inspectable, and the disagreement is reported.
    assert {item["source_id"] for item in selection.alternatives} == {
        first["source"]["source_id"], second["source"]["source_id"],
    } - {expected}
    assert selection.conflict is True

    summary = prices.price_summary(db, security)
    comparison = prices.price_on_or_before(db, security, DAY)
    assert summary["source"]["source_id"] == selection.selected_source_id
    assert comparison["source_id"] == selection.selected_source_id
    assert summary["source_selection"]["observation_id"] == comparison["observation_id"]
    assert summary["latest_close"] == comparison["close"]


def test_markets_read_model_and_price_summary_agree(db):
    master, _, security, _ = _identity(db)
    _import(db, close=10.0, source="Provider A", day="2024-12-30")
    _import(db, close=11.5, source="Provider A", day=DAY)

    summary = prices.price_summary(db, security)
    row = read_models._security_summary(master, db, _security_dict(db, security))
    assert row["last_close"] == Decimal(str(summary["latest_close"]))
    assert row["last_bar_date"] == summary["latest_session"]
    assert row["sessions"] == summary["observations"]


def test_issuer_metrics_price_links_to_the_immutable_observation(db):
    master, issuer, security, _ = _identity(db)
    _import(db, close=10.0)
    summary = prices.price_summary(db, security)

    payload = read_models.issuer_metrics(db, issuer)
    assert payload["price"] == summary["latest_close"]
    assert payload["price_as_of"] == summary["latest_session"]
    assert payload["price_observation_id"] == summary["source_selection"]["observation_id"]
    assert payload["price_source_selection"]["policy"] == prices.SOURCE_SELECTION_POLICY


def test_a_provider_correction_moves_the_summary_but_not_a_saved_pin(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    original = prices.price_on_or_before(db, security, DAY)
    pin = original["pin"]

    _import(db, close=11.0)
    corrected = prices.price_summary(db, security)
    assert corrected["latest_close"] == 11.0
    assert corrected["source"]["revision_seq"] == 2
    assert corrected["source_selection"]["observation_id"] != original["observation_id"]

    replay = prices.price_for_pin(db, pin)
    assert replay["status"] == "exact"
    assert replay["price"]["close"] == 10.0
    assert replay["observation"]["observation_id"] == pin["observation_id"]


def test_explicit_source_selects_only_that_provider(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0, source="Provider A")
    second = _import(db, close=12.0, source="Provider B")
    chosen = second["source"]["source_id"]

    selection = _selection(db, security, source_id=chosen)
    assert selection.requested_policy == "explicit_source"
    assert selection.observation is not None
    assert selection.observation.close == Decimal("12.0")
    comparison = prices.price_on_or_before(db, security, DAY, source_id=chosen)
    assert comparison["close"] == 12.0
    assert comparison["source_id"] == chosen


def test_missing_source_identity_is_a_policy_error_not_a_guess(db):
    _, _, security, _ = _identity(db)
    _import(db, close=10.0)
    with pytest.raises(prices.PriceImportError):
        prices.price_on_or_before(db, security, DAY, policy="explicit_source")


def test_listing_constraint_keeps_venues_separate(db):
    master, _, security, _ = _identity(db)
    second_listing = master.ensure_listing(security, "XNAS", valid_from="2020-01-01")
    master.assign_ticker(
        second_listing, "TSTN", valid_from="2020-01-01", confidence=1.0,
        status="confirmed", source_id="sec-edgar",
    )
    _import(db, close=10.0, mic="XNYS")
    _import(db, close=20.0, mic="XNAS", ticker="TSTN")

    nyse = prices.price_on_or_before(db, security, DAY, mic="XNYS")
    nasdaq = prices.price_on_or_before(db, security, DAY, mic="XNAS")
    assert nyse["close"] == 10.0 and nyse["mic"] == "XNYS"
    assert nasdaq["close"] == 20.0 and nasdaq["mic"] == "XNAS"
    assert nyse["observation_id"] != nasdaq["observation_id"]


def test_synthetic_source_stays_labelled_across_consumers(db):
    _, issuer, security, _ = _identity(db)
    _import(db, close=10.0, source="Project fixture", licence="CC0-1.0",
            redistribution="public_domain", collection_method="synthetic_fixture",
            authorization_basis="project-authored synthetic fixture")

    selection = _selection(db, security)
    assert selection.observation.source_kind == "synthetic"
    summary = prices.price_summary(db, security)
    assert summary["source"]["redistribution"] == "public_domain"

    from atlas.research.equity import EquityResearchService
    coverage = EquityResearchService(db)._issuer_coverage(
        dict(db.query_one("SELECT * FROM issuer WHERE issuer_id = ?", (issuer,)))
    )
    assert coverage["price_source"] == "synthetic"


def test_restricted_observation_is_analysable_but_not_redistributable(db):
    _, issuer, security, _ = _identity(db)
    _import(db, close=10.0)
    selection = _selection(db, security)
    assert selection.observation.export_allowed is False

    engine = DataRightsEngine(db)
    decision = engine.decisions_for_sources([selection.selected_source_id])[0]
    assert decision["actions"]["analysis"]["allowed"] is True
    assert decision["actions"]["export"]["allowed"] is False
    assert decision["packaging_allowed"] is False
    with pytest.raises(Exception):
        engine.assert_packaging([selection.selected_source_id])


# ------------------------------------------------------------------- rights
def test_unknown_rights_permit_nothing(db):
    decision = DataRightsEngine.decisions_for_metadata(
        [{"source_id": "src-x", "redistribution": None}]
    )[0]
    assert decision["redistribution"] == "unknown"
    assert not any(item["allowed"] for item in decision["actions"].values())
    assert decision["packaging_allowed"] is False
    assert data_rights.classify(None)["trusted"] is False


def test_permissive_licence_is_not_a_public_domain_dedication():
    decision = data_rights.classify("public_domain", copyright_licence="Apache-2.0")
    assert decision["redistribution"] == "project_authored"
    assert decision["export_allowed"] is True
    assert any("public-domain" in warning for warning in decision["warnings"])


def test_public_domain_dedication_remains_exportable():
    decision = data_rights.classify("public_domain", copyright_licence="CC0-1.0")
    assert decision["redistribution"] == "public_domain"
    assert decision["export_allowed"] is True


def test_two_rights_engines_reach_the_same_verdict():
    for declared in (None, "", "restricted", "user_responsibility", "public_domain", "permitted"):
        research = data_rights.classify(declared, copyright_licence="CC0-1.0")
        enforced = DataRightsEngine.decisions_for_metadata(
            [{"source_id": "s", "redistribution": declared, "licence": "CC0-1.0"}]
        )[0]
        assert enforced["redistribution"] == research["redistribution"]
        assert enforced["packaging_allowed"] is research["export_allowed"]


# ------------------------------------------------------------------ exposure
def test_every_loopback_form_is_permitted_without_a_flag():
    for host in ("127.0.0.1", "127.0.0.2", "::1", "localhost"):
        decision = assess_bind(host, environ={})
        assert decision["permitted"] is True
        assert decision["warning"] is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.1.2.3", "192.168.1.10", "example.com"])
def test_non_loopback_binding_is_refused_without_acknowledgement(host):
    decision = assess_bind(host, environ={})
    assert decision["permitted"] is False
    assert decision["authentication"] == "absent"
    assert "refusing" in str(decision["reason"])


def test_acknowledgement_permits_binding_but_is_not_authentication():
    decision = assess_bind("0.0.0.0", allow_non_loopback=True, environ={})
    assert decision["permitted"] is True
    assert decision["warning"] and "not authentication" in decision["warning"]
    assert decision["authentication"] == "absent"


def test_environment_acknowledgement_is_explicit_only():
    assert assess_bind("0.0.0.0", environ={ACK_ENV: "1"})["permitted"] is True
    for value in ("0", "no", "", "false"):
        assert assess_bind("0.0.0.0", environ={ACK_ENV: value})["permitted"] is False


# ------------------------------------------------------------- compatibility
def test_current_operator_versions_resolve():
    report = compatibility.compatibility_report(
        compiler_version=COMPILER_VERSION, operators=operator_versions()
    )
    assert report["compatible"] is True
    assert report["operators_checked"] == len(REGISTRY)
    assert report["mismatches"] == []


def test_unknown_operator_fails_closed():
    with pytest.raises(compatibility.IncompatibleModelVersion) as excinfo:
        compatibility.resolve_operator("operator_that_never_existed", "v1")
    assert excinfo.value.report["status"] == compatibility.STATUS_UNKNOWN


def test_operator_version_mismatch_fails_closed():
    name = sorted(REGISTRY)[0]
    with pytest.raises(compatibility.IncompatibleModelVersion) as excinfo:
        compatibility.resolve_operator(name, "atlas.fec.operators.v0")
    assert excinfo.value.report["status"] == compatibility.STATUS_OPERATOR_MISMATCH


def test_persisted_package_operator_versions_still_resolve():
    from atlas.applications.contracts import dependency_diagnostics

    application = {
        "runtime": {"kind": "fec_model"},
        "dependencies": {
            "compiler_version": COMPILER_VERSION,
            "operators": [
                {"name": name, "version": version}
                for name, version in sorted(operator_versions().items())
            ],
        },
    }
    assert dependency_diagnostics(application) == []

    stale = {
        "runtime": {"kind": "fec_model"},
        "dependencies": {
            "compiler_version": COMPILER_VERSION,
            "operators": [{"name": sorted(REGISTRY)[0], "version": "atlas.fec.operators.v0"}],
        },
    }
    codes = {item["code"] for item in dependency_diagnostics(stale)}
    assert "operator_version_conflict" in codes
