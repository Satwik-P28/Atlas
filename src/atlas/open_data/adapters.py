"""Provider-format adapters.

An adapter does two jobs and nothing else:

1. produce *validation statistics* (members, rows, entities, observation range),
2. yield typed :class:`~atlas.open_data.index.Observation` records where the dataset
   has a documented tabular shape.

It never invents a publication date. When a provider does not publish a revision
timestamp, ``published_at`` stays ``None`` and the observation records
``availability_basis = "publication_date_unknown"``; only the ingestion time is known.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from . import archives
from .index import Observation

# SEC notes archives contain large free-text cells; the stdlib default (128 KiB)
# aborts the whole parse rather than reporting a field. Raise it explicitly.
csv.field_size_limit(64 * 1024 * 1024)

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%Y-%m", "%Y", "%d/%m/%Y", "%m/%d/%y")

#: Computed once: provider loops can call note_range hundreds of millions of times.
_TODAY = date.today().isoformat()
_MAX_PLAUSIBLE_DATE = (date.today() + timedelta(days=730)).isoformat()


@lru_cache(maxsize=262_144)
def normalise_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "")
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def decimal_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if text in {"", ".", "NA", "N/A", "null", "None", "--", "(D)", "(NA)"}:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return format(number.normalize(), "f") if number == number.to_integral() else str(number)


def slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return cleaned or "value"


def bls_period_date(year: Any, period: Any) -> tuple[str | None, str | None, str | None]:
    """Map a BLS year/period pair to an observation date and a period label.

    M13 is the annual average; Q05 is annual. Neither is a calendar month, so the
    period end is the last day of the represented span and the label is preserved.
    """
    try:
        year_int = int(str(year).strip())
    except (TypeError, ValueError):
        return None, None, None
    raw = str(period or "").strip().upper()
    if not raw:
        return None, None, None
    if raw.startswith("M") and raw[1:].isdigit():
        month = int(raw[1:])
        if 1 <= month <= 12:
            day = 28 if month == 2 else 30 if month in {4, 6, 9, 11} else 31
            return f"{year_int:04d}-{month:02d}-{day:02d}", f"{year_int:04d}-{month:02d}-01", raw
        if month == 13:
            return f"{year_int:04d}-12-31", f"{year_int:04d}-01-01", raw
    if raw.startswith("Q") and raw[1:].isdigit():
        quarter = int(raw[1:])
        if 1 <= quarter <= 4:
            month = quarter * 3
            day = 31 if month in {3, 12} else 30
            return f"{year_int:04d}-{month:02d}-{day:02d}", f"{year_int:04d}-{(quarter - 1) * 3 + 1:02d}-01", raw
        if quarter == 5:
            return f"{year_int:04d}-12-31", f"{year_int:04d}-01-01", raw
    if raw.startswith("A") and raw[1:].isdigit():
        return f"{year_int:04d}-12-31", f"{year_int:04d}-01-01", raw
    if raw.startswith("S") and raw[1:].isdigit():
        half = int(raw[1:])
        if half in {1, 2}:
            month = 6 if half == 1 else 12
            return f"{year_int:04d}-{month:02d}-{'30' if half == 1 else '31'}", f"{year_int:04d}-{(half - 1) * 6 + 1:02d}-01", raw
    if raw.startswith("W") and raw[1:].isdigit():
        return None, None, raw
    return None, None, raw


@dataclass(slots=True)
class Analysis:
    record_count: int = 0
    entity_count: int = 0
    series_count: int = 0
    obs_start: str | None = None
    obs_end: str | None = None
    decompressed_bytes: int = 0
    file_count: int = 0
    publications: int = 0
    implausible_dates: int = 0
    future_dates: int = 0
    observations: list[Observation] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    derived: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def note_range(self, value: str | None) -> None:
        """Track the plausible provider observation range.

        Values outside 1900-01-01 .. today+2 years are counted separately. They are
        retained in the raw snapshot (nothing is rewritten) but they must not become
        the advertised coverage of the dataset: a filer typo of 6016 is not history.
        """
        if not value:
            return
        if value < "1900-01-01" or value > _MAX_PLAUSIBLE_DATE:
            self.implausible_dates += 1
            return
        if value > _TODAY:
            # A future period end is a scheduled period, not observed history.
            self.future_dates += 1
            return
        if self.obs_start is None or value < self.obs_start:
            self.obs_start = value
        if self.obs_end is None or value > self.obs_end:
            self.obs_end = value

    def to_stats(self, dataset_id: str) -> dict[str, Any]:
        stats = {
            "dataset_id": dataset_id,
            "record_count": self.record_count,
            "entity_count": self.entity_count,
            "series_count": self.series_count,
            "obs_start": self.obs_start,
            "obs_end": self.obs_end,
            "decompressed_bytes": self.decompressed_bytes,
            "file_count": self.file_count,
            "publications_with_dates": self.publications,
            "implausible_observation_dates": self.implausible_dates,
            "future_observation_dates": self.future_dates,
            "issues": self.issues,
        }
        stats.update(self.extra)
        return stats


def _open_member(path: Path, name: str):
    if path.suffix == ".gz" and not name.endswith(".tar"):
        return gzip.open(path, "rb")
    return None


def _iter_zip_members(path: Path) -> Iterator[tuple[str, io.BufferedIOBase, int]]:
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            archives._safe_name(info.filename)
            with archive.open(info) as stream:
                yield info.filename, stream, info.file_size


def _iter_tar_members(path: Path) -> Iterator[tuple[str, io.BufferedIOBase, int]]:
    with tarfile.open(path, "r:*") as archive:
        for info in archive.getmembers():
            if not info.isfile():
                continue
            archives._safe_name(info.name)
            stream = archive.extractfile(info)
            if stream is not None:
                with stream:
                    yield info.name, stream, info.size


def iter_members(path: Path) -> Iterator[tuple[str, io.BufferedIOBase, int]]:
    fmt = archives.detect_format(path)
    if fmt == "zip":
        yield from _iter_zip_members(path)
    elif fmt == "tar":
        yield from _iter_tar_members(path)
    elif fmt == "gzip":
        yield path.name[:-3] if path.name.endswith(".gz") else path.name, gzip.open(path, "rb"), path.stat().st_size
    else:
        yield path.name, open(path, "rb"), path.stat().st_size


# --------------------------------------------------------------------------- #
# Tabular
# --------------------------------------------------------------------------- #
def _decode(stream) -> io.TextIOWrapper:
    return io.TextIOWrapper(stream, encoding="utf-8-sig", errors="replace", newline="")


def analyze_tabular(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                    analysis: Analysis) -> None:
    parse = dict(dataset.get("parse") or {})
    filename = parse.get("filename")
    candidates = [name for name in snapshot_files if filename and name.endswith(filename)] or list(snapshot_files)
    if not candidates:
        analysis.issues.append({"code": "no_files", "severity": "error", "detail": "snapshot has no tabular file"})
        return
    name = candidates[0]
    path = snapshot_files[name]
    delimiter = "\t" if (parse.get("delimiter") == "\t" or path.suffix in {".tsv"} or
                          any(path.name.endswith(ext) for ext in (".AllData", ".Current"))) else ","
    max_obs = int(parse.get("max_observations") or 2_000_000)
    mode = parse.get("mode", "wide")
    headers: list[str] = []
    rows = 0
    series: set[str] = set()
    with path.open("rb") as raw:
        text = _decode(raw)
        first_line = text.readline()
        if "\t" in first_line and first_line.count("\t") >= first_line.count(","):
            delimiter = "\t"
        text.seek(0)
        reader = csv.reader(text, delimiter=delimiter)
        headers = next(reader, [])
        headers = [h.strip() for h in headers]
        date_col = parse.get("date_column") or (headers[0] if headers else "")
        date_index = headers.index(date_col) if date_col in headers else 0
        if mode == "narrow":
            series_index = headers.index(parse["series_column"])
            value_index = headers.index(parse["value_column"])
            year_index = headers.index(parse["year_column"]) if parse.get("year_column") else None
            period_index = headers.index(parse["period_column"]) if parse.get("period_column") else None
        value_columns = parse.get("value_columns")
        if mode == "wide" and value_columns is None:
            value_columns = [h for i, h in enumerate(headers) if i != date_index]
        for row in reader:
            rows += 1
            if rows > int(parse.get("max_rows") or 5_000_000):
                analysis.issues.append({"code": "row_limit", "severity": "warning",
                                        "detail": f"stopped after {rows} rows"})
                break
            if len(row) < max(1, len(headers)):
                row = row + [""] * (len(headers) - len(row))
            obs_date = normalise_date(row[date_index]) if date_index < len(row) else None
            if not obs_date and year_index is not None:
                obs_date, period_start, period = bls_period_date(
                    row[year_index] if year_index < len(row) else None,
                    row[period_index] if period_index is not None and period_index < len(row) else None,
                )
                if len(analysis.observations) < max_obs and obs_date:
                    value = decimal_text(row[value_index]) if value_index < len(row) else None
                    series_id = (row[series_index] if series_index < len(row) else "").strip()
                    if value is not None and series_id:
                        series.add(series_id)
                        analysis.observations.append(Observation(
                            dataset_id=dataset["id"], series_key=series_id, obs_date=obs_date,
                            period_start=period_start, value_numeric=value,
                            unit=parse.get("unit"), source_url=dataset.get("download_endpoint"),
                            availability_basis="publication_date_unknown",
                        ))
                continue
            analysis.note_range(obs_date)
            if len(analysis.observations) >= max_obs:
                continue
            if mode == "narrow":
                value = decimal_text(row[value_index]) if value_index < len(row) else None
                series_id = (row[series_index] if series_index < len(row) else "").strip()
                if value is None or not series_id:
                    continue
                series.add(series_id)
                analysis.observations.append(Observation(
                    dataset_id=dataset["id"], series_key=series_id, obs_date=obs_date,
                    value_numeric=value, unit=parse.get("unit"),
                    source_url=dataset.get("download_endpoint"),
                ))
            else:
                for column in value_columns:
                    if column not in headers:
                        continue
                    index = headers.index(column)
                    value = decimal_text(row[index]) if index < len(row) else None
                    if value is None:
                        continue
                    key = f"{dataset['id']}.{slug(column)}"
                    series.add(key)
                    analysis.observations.append(Observation(
                        dataset_id=dataset["id"], series_key=key, obs_date=obs_date,
                        value_numeric=value, unit=parse.get("unit"),
                        source_url=dataset.get("download_endpoint"),
                    ))
    analysis.record_count = rows
    analysis.entity_count = int(parse.get("entity_count") or 0)
    analysis.series_count = len(series)
    analysis.file_count = 1
    analysis.extra.update({"columns": headers[:50], "mode": mode, "delimiter": "tab" if delimiter == "\t" else "comma"})


# --------------------------------------------------------------------------- #
# Fiscal Data API pages
# --------------------------------------------------------------------------- #
def analyze_fiscal_api(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                       analysis: Analysis) -> None:
    parse = dict(dataset.get("parse") or {})
    rows = 0
    series: set[str] = set()
    fields = parse.get("value_fields")
    date_field = parse.get("date_field") or "record_date"
    page_names = sorted(name for name in snapshot_files if name.endswith(".json"))
    for name in page_names:
        payload = json.loads(snapshot_files[name].read_text(encoding="utf-8"))
        records = payload.get("data")
        if not isinstance(records, list):
            analysis.issues.append({"code": "bad_page", "severity": "error", "detail": f"{name} has no data list"})
            continue
        for record in records:
            rows += 1
            obs_date = normalise_date(record.get(date_field))
            analysis.note_range(obs_date)
            for field in fields or []:
                value = decimal_text(record.get(field))
                if value is None:
                    continue
                key = f"{dataset['id']}.{slug(field)}"
                series.add(key)
                analysis.observations.append(Observation(
                    dataset_id=dataset["id"], series_key=key, obs_date=obs_date,
                    value_numeric=value, unit=parse.get("unit"),
                    published_at=None, availability_basis="publication_date_unknown",
                    source_url=dataset.get("download_endpoint"),
                ))
    analysis.record_count = rows
    analysis.series_count = len(series)
    analysis.file_count = len(page_names)
    analysis.extra["pages"] = len(page_names)


# --------------------------------------------------------------------------- #
# Generic JSON APIs (FDIC BankFind, GLEIF, ...)
# --------------------------------------------------------------------------- #
def analyze_json_api(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                     analysis: Analysis) -> None:
    parse = dict(dataset.get("parse") or {})
    data_path = parse.get("data_path") or "data"
    date_field = parse.get("date_field")
    id_field = parse.get("id_field")
    numeric_fields = parse.get("value_fields") or []
    rows = 0
    entities: set[str] = set()
    series: set[str] = set()
    for name in sorted(snapshot_files):
        if not name.endswith(".json"):
            continue
        payload = json.loads(snapshot_files[name].read_text(encoding="utf-8"))
        for key in data_path.split("."):
            payload = payload.get(key) if isinstance(payload, Mapping) else None
        if not isinstance(payload, list):
            continue
        wrapper = parse.get("record_wrapper")
        for record in payload:
            if not isinstance(record, Mapping):
                continue
            if wrapper and isinstance(record.get(wrapper), Mapping):
                record = record[wrapper]
            rows += 1
            entity = str(record.get(id_field)) if id_field and record.get(id_field) is not None else None
            if entity:
                entities.add(entity)
            obs_date = normalise_date(record.get(date_field)) if date_field else None
            analysis.note_range(obs_date)
            for field in numeric_fields:
                value = decimal_text(record.get(field))
                if value is None:
                    continue
                key = f"{dataset['id']}.{slug(field)}"
                series.add(key)
                analysis.observations.append(Observation(
                    dataset_id=dataset["id"], series_key=key, obs_date=obs_date,
                    value_numeric=value, entity_id=entity, unit=parse.get("unit"),
                    published_at=None, availability_basis="publication_date_unknown",
                    source_url=dataset.get("download_endpoint"),
                ))
    analysis.record_count = rows
    analysis.entity_count = len(entities)
    analysis.series_count = len(series)
    analysis.file_count = len(snapshot_files)


def analyze_worldbank(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                      analysis: Analysis) -> None:
    rows = 0
    entities: set[str] = set()
    series: set[str] = set()
    for name in sorted(snapshot_files):
        if not name.endswith(".json"):
            continue
        payload = json.loads(snapshot_files[name].read_text(encoding="utf-8"))
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
            continue
        for record in payload[1]:
            rows += 1
            country = record.get("countryiso3code") or (record.get("country") or {}).get("id")
            indicator = (record.get("indicator") or {}).get("id") or dataset["id"]
            if country:
                entities.add(str(country))
            obs_date = normalise_date(record.get("date"))
            analysis.note_range(obs_date)
            value = decimal_text(record.get("value"))
            if value is None:
                continue
            key = f"{dataset['id']}.{indicator}"
            series.add(key)
            analysis.observations.append(Observation(
                dataset_id=dataset["id"], series_key=key, obs_date=obs_date,
                entity_id=str(country) if country else None, value_numeric=value,
                source_url=dataset.get("download_endpoint"),
            ))
    analysis.record_count = rows
    analysis.entity_count = len(entities)
    analysis.series_count = len(series)


# --------------------------------------------------------------------------- #
# SEC bulk archives
# --------------------------------------------------------------------------- #
def analyze_sec_companyfacts(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                             analysis: Analysis) -> None:
    parse = dict(dataset.get("parse") or {})
    limit = int(parse.get("max_entities") or 0)
    extract = bool(parse.get("extract_observations"))
    concepts = set(parse.get("concepts") or [])
    max_obs = int(parse.get("max_observations") or 0)
    companies = 0
    facts = 0
    sample_company_facts: list[dict[str, Any]] = []
    for name, stream, size in iter_members(snapshot_files["companyfacts.zip"]):
        if not name.endswith(".json"):
            continue
        if limit and companies >= limit:
            break
        try:
            payload = json.loads(stream.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            analysis.issues.append({"code": "malformed_companyfacts", "severity": "error",
                                    "detail": f"{name}: {exc}"})
            continue
        companies += 1
        analysis.decompressed_bytes += size
        cik = payload.get("cik")
        company_facts = 0
        namespaces = payload.get("facts") or {}
        if isinstance(namespaces, Mapping):
            for namespace, elements in namespaces.items():
                if not isinstance(elements, Mapping):
                    continue
                for tag, element in elements.items():
                    units = (element or {}).get("units") if isinstance(element, Mapping) else None
                    if not isinstance(units, Mapping):
                        continue
                    for unit, observations in units.items():
                        for observation in observations or []:
                            facts += 1
                            company_facts += 1
                            end = observation.get("end")
                            if end:
                                analysis.note_range(str(end))
                            if extract and len(analysis.observations) < max_obs:
                                concept = f"{namespace}:{tag}"
                                if len(analysis.observations) + 1 == max_obs:
                                    analysis.extra["observation_limit_applied"] = max_obs
                                    analysis.extra["sampled"] = True
                                if concepts and concept not in concepts:
                                    continue
                                value = decimal_text(observation.get("val"))
                                if value is None:
                                    continue
                                analysis.observations.append(Observation(
                                    dataset_id=dataset["id"], series_key=f"us-gaap:{tag}",
                                    entity_id=f"CIK{cik:010d}" if isinstance(cik, int) else str(cik),
                                    concept=concept, obs_date=normalise_date(end),
                                    period_start=normalise_date(observation.get("start")),
                                    period_end=normalise_date(end), value_numeric=value,
                                    unit=str(unit), published_at=None,
                                    provider_revision_at=normalise_date(observation.get("filed")),
                                    availability_basis="filed_date_known_acceptance_unknown",
                                    source_url=dataset.get("download_endpoint"),
                                ))
        if len(sample_company_facts) < 25:
            sample_company_facts.append({"cik": cik, "name": payload.get("entityName"), "facts": company_facts})
    analysis.record_count = facts
    analysis.entity_count = companies
    analysis.series_count = len({o.series_key for o in analysis.observations})
    analysis.file_count = companies
    analysis.extra["sample_companies"] = sample_company_facts
    if limit:
        analysis.extra["entity_limit_applied"] = limit


def analyze_sec_submissions(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                            analysis: Analysis) -> None:
    parse = dict(dataset.get("parse") or {})
    limit = int(parse.get("max_entities") or 0)
    companies = 0
    filings = 0
    forms: dict[str, int] = {}
    for name, stream, size in iter_members(snapshot_files["submissions.zip"]):
        if not name.endswith(".json"):
            continue
        if limit and companies >= limit:
            break
        try:
            payload = json.loads(stream.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            analysis.issues.append({"code": "malformed_submission", "severity": "error",
                                    "detail": f"{name}: {exc}"})
            continue
        companies += 1
        analysis.decompressed_bytes += size
        recent = payload.get("filings", {}).get("recent", {})
        if isinstance(recent, Mapping):
            accession = recent.get("accessionNumber") or []
            form_values = recent.get("form") or []
            filing_dates = recent.get("filingDate") or []
            for index in range(len(accession)):
                filings += 1
                form = str(form_values[index]) if index < len(form_values) else "UNKNOWN"
                forms[form] = forms.get(form, 0) + 1
                if index < len(filing_dates):
                    analysis.note_range(str(filing_dates[index]))
    analysis.record_count = filings
    analysis.entity_count = companies
    analysis.file_count = companies
    analysis.extra["form_distribution"] = dict(sorted(forms.items(), key=lambda item: -item[1])[:25])


def analyze_cftc(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                 analysis: Analysis) -> None:
    rows = 0
    files_seen = 0
    for filename, path in snapshot_files.items():
        if archives.detect_format(path) in {"zip", "tar", "gzip"}:
            members = iter_members(path)
        else:
            members = [(filename, open(path, "rb"), path.stat().st_size)]
        for member_name, raw, size in members:
            if not member_name.lower().endswith((".txt", ".csv")):
                continue
            files_seen += 1
            analysis.decompressed_bytes += size
            text = _decode(raw)
            reader = csv.reader(text, delimiter=",")
            header = next(reader, [])
            date_index = next((i for i, h in enumerate(header) if "report_date" in h.lower()), None)
            for row in reader:
                rows += 1
                if date_index is not None and date_index < len(row):
                    analysis.note_range(normalise_date(row[date_index]))
    analysis.record_count = rows
    analysis.file_count = files_seen


def analyze_archive(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                    analysis: Analysis) -> None:
    parse = dict(dataset.get("parse") or {})
    for name, path in snapshot_files.items():
        fmt = archives.detect_format(path)
        if fmt in {"zip", "tar", "gzip"}:
            inspection = archives.inspect(path)
            analysis.record_count += inspection.members
            analysis.decompressed_bytes += inspection.uncompressed_bytes
            analysis.extra.setdefault("archives", {})[name] = inspection.to_dict()
            analysis.file_count += inspection.members
        elif fmt == "json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                count = len(payload)
            elif isinstance(payload, Mapping) and isinstance(payload.get("data"), list):
                count = len(payload["data"])
                analysis.entity_count = max(analysis.entity_count, count)
            else:
                count = 1
            analysis.record_count += count
            analysis.file_count += 1
    analysis.series_count = int(parse.get("series_count") or 0)


def analyze_sec_financial_statements(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                                     analysis: Analysis) -> None:
    """SEC Financial Statement Data Sets (sub.txt + num.txt) or monthly notes archives."""
    rows = 0
    entities: set[str] = set()
    series: set[str] = set()
    parse = dict(dataset.get("parse") or {})
    # A historical series can contain dozens of quarterly archives. Counting every
    # num.txt row would take hours and add little to a filing census, so the caller may
    # restrict the census to named members. The restriction is recorded, never hidden.
    census_members = tuple(str(item).lower() for item in (parse.get("count_members") or []))
    if census_members:
        analysis.extra["census_members"] = list(census_members)
    for filename, path in snapshot_files.items():
        if archives.detect_format(path) not in {"zip", "tar", "gzip"}:
            continue
        inspection = archives.inspect(path)
        analysis.decompressed_bytes += inspection.uncompressed_bytes
        for member_name, raw, size in iter_members(path):
            lowered = member_name.lower()
            if not lowered.endswith((".txt", ".tsv", ".csv")):
                continue
            if census_members and not any(lowered.endswith(item) for item in census_members):
                continue
            text = _decode(raw)
            reader = csv.reader(text, delimiter="\t")
            header = [h.strip().lower() for h in next(reader, [])]
            if not header:
                continue
            adsh_index = header.index("adsh") if "adsh" in header else None
            cik_index = header.index("cik") if "cik" in header else None
            date_index = next((header.index(name) for name in ("period", "filed", "ddate")
                               if name in header), None)
            tag_index = header.index("tag") if "tag" in header else None
            for row in reader:
                rows += 1
                if cik_index is not None and cik_index < len(row) and row[cik_index].strip():
                    entities.add(row[cik_index].strip())
                if date_index is not None and date_index < len(row):
                    analysis.note_range(normalise_date(row[date_index]))
                if tag_index is not None and tag_index < len(row) and row[tag_index].strip():
                    series.add(row[tag_index].strip())
            if adsh_index is not None:
                analysis.extra.setdefault("submission_columns", header[:30])
    analysis.record_count = rows
    analysis.entity_count = len(entities)
    analysis.series_count = len(series)
    analysis.file_count = len(snapshot_files)


def analyze_eia_bulk(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path],
                     analysis: Analysis) -> None:
    """EIA bulk archives are ZIPs of newline-delimited JSON series objects."""
    rows = 0
    series: set[str] = set()
    for filename, path in snapshot_files.items():
        if archives.detect_format(path) not in {"zip", "tar", "gzip"}:
            continue
        inspection = archives.inspect(path)
        analysis.decompressed_bytes += inspection.uncompressed_bytes
        for member_name, raw, size in iter_members(path):
            if not member_name.lower().endswith((".txt", ".json")):
                continue
            for line in _decode(raw):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, Mapping):
                    continue
                rows += 1
                if record.get("series_id"):
                    series.add(str(record["series_id"]))
                for data_point in record.get("data") or []:
                    if isinstance(data_point, list) and len(data_point) >= 2:
                        analysis.note_range(normalise_date(data_point[0]))
    analysis.record_count = rows
    analysis.series_count = len(series)
    analysis.file_count = len(snapshot_files)


ANALYZERS = {
    "tabular": analyze_tabular,
    "fiscal_api": analyze_fiscal_api,
    "json_api": analyze_json_api,
    "worldbank": analyze_worldbank,
    "sec_companyfacts": analyze_sec_companyfacts,
    "sec_submissions": analyze_sec_submissions,
    "sec_financial_statements": analyze_sec_financial_statements,
    "eia_bulk": analyze_eia_bulk,
    "cftc": analyze_cftc,
    "archive": analyze_archive,
}


def analyze(dataset: Mapping[str, Any], snapshot_files: Mapping[str, Path]) -> Analysis:
    adapter = str(dataset.get("adapter") or "archive")
    analysis = Analysis()
    try:
        ANALYZERS[adapter](dataset, snapshot_files, analysis)
    except KeyError:
        raise ValueError(f"unknown adapter {adapter!r} for {dataset.get('id')}")
    except Exception as exc:  # adapter failure becomes evidence, not a published snapshot
        analysis.issues.append({"code": "adapter_failure", "severity": "error",
                                "detail": f"{type(exc).__name__}: {exc}"})
        raise
    return analysis
