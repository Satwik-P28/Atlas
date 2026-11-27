"""Release policy, input validation and publication truth.

Three separate concerns live here on purpose:

* **Input validation.** A release workflow receives strings from a human. Those
  strings are validated against the registry and a strict grammar *before* they
  reach a shell, a filename or an HTTP call. Unknown datasets and unsafe
  arguments are rejected, never sanitised into something that looks valid.
* **The asset catalogue.** What is discovered, rights-approved, acquired,
  locally available, packaged, uploaded, independently downloaded, restored and
  integrated are nine different facts. Collapsing them into "released" is how a
  project ends up claiming durability for a hash that only exists in Git.
* **Publication records.** The catalogue is read from the release index in Git,
  the local store, the open-data index database and (optionally) the GitHub
  Releases API. A failed publication is preserved as a record instead of being
  overwritten by the next attempt.

Nothing in this module uploads bytes. Publication remains an explicitly
authorised step.
"""

from __future__ import annotations

import json
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .registry import Registry
from .rights import evaluate
from .store import SnapshotStore

DEFAULT_REPO = "Satwik-P28/Atlas"
RELEASES_DIR = Path(__file__).resolve().parents[3] / "data/open_data/releases"
DEFAULT_INDEX = RELEASES_DIR / "index.json"
DEFAULT_DOWNLOADS = RELEASES_DIR / "downloads.json"
DEFAULT_PUBLICATIONS = RELEASES_DIR / "publications"

#: GitHub rejects assets above 2 GiB. Atlas targets 1.9 GB so a package built on
#: one filesystem still uploads from another, and so the multipart split has
#: headroom for container overhead.
MAX_ASSET_BYTES = 1_900_000_000

#: Dataset ids are registry ids, never free text.
DATASET_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9][a-z0-9_-]*)+$")
#: `open-data-2026-11` and an explicit re-release `open-data-2026-11-r2`.
TAG_RE = re.compile(r"^open-data-\d{4}-(?:0[1-9]|1[0-2])(?:-r[1-9][0-9]{0,2})?$")
#: A release asset name: no slashes, no leading dot, no shell metacharacters.
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseInputError(ValueError):
    """A release input is unknown, unsafe or inconsistent with the registry."""


class ReleaseLookupError(RuntimeError):
    """The published release could not be read; availability stays unknown."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------- validation
def dataset_decisions(registry: Registry) -> dict[str, dict[str, Any]]:
    """The current publication decision for every registered dataset."""
    decisions: dict[str, dict[str, Any]] = {}
    for dataset in registry:
        decision = evaluate(dataset.raw, "publish", public_distribution=True)
        decisions[dataset.id] = {
            "allowed": bool(decision.allowed),
            "reason": decision.reason,
            "rights_class": dataset.rights_class.value,
            "title": dataset["title"],
            "provider": dataset.provider,
        }
    return decisions


def allowed_dataset_ids(registry: Registry) -> set[str]:
    """Datasets the *current* registry permits packaging and publishing."""
    return {dataset_id for dataset_id, item in dataset_decisions(registry).items() if item["allowed"]}


def validate_dataset_ids(raw: str | Sequence[str], registry: Registry) -> list[str]:
    """Parse and validate release dataset ids.

    ``raw`` is either the workflow input (space separated) or an argv list. A
    dataset that is unknown to the registry, malformed, denied by the current
    rights decision or duplicated is an error: a release must not silently drop
    a dataset the operator asked for.
    """
    if isinstance(raw, str):
        candidates = raw.split()
    else:
        candidates = [str(item) for item in raw]
    if not candidates:
        raise ReleaseInputError("no dataset ids were supplied")
    decisions = dataset_decisions(registry)
    selected: list[str] = []
    problems: list[str] = []
    for candidate in candidates:
        if not DATASET_RE.match(candidate):
            problems.append(f"malformed dataset id {candidate!r}")
            continue
        if candidate not in decisions:
            problems.append(f"unknown dataset {candidate!r} is not in the registry")
            continue
        if not decisions[candidate]["allowed"]:
            problems.append(f"{candidate} is not redistributable: {decisions[candidate]['reason']}")
            continue
        if candidate in selected:
            problems.append(f"duplicate dataset id {candidate!r}")
            continue
        selected.append(candidate)
    if problems:
        raise ReleaseInputError("; ".join(problems))
    return selected


def validate_tag(tag: str) -> str:
    if not isinstance(tag, str) or not TAG_RE.match(tag):
        raise ReleaseInputError(
            f"release tag {tag!r} must look like open-data-YYYY-MM or open-data-YYYY-MM-rN"
        )
    return tag


def validate_filenames(values: Iterable[str], *, allowed_dataset_ids: Iterable[str]) -> list[str]:
    """Validate asset filenames against the grammar and the allowed datasets."""
    allowed = tuple(sorted(set(allowed_dataset_ids), key=len, reverse=True))
    accepted: list[str] = []
    for value in values:
        name = str(value)
        if not FILENAME_RE.match(name) or name.startswith(".") or ".." in name:
            raise ReleaseInputError(f"unsafe release asset filename {name!r}")
        if not any(name == f"{dataset_id}{suffix}" or name.startswith(f"{dataset_id}.part-")
                   or name.startswith(f"{dataset_id}-period-") for dataset_id in allowed
                   for suffix in (".tar.zst", ".tar.zst.sha256", ".index.json", ".parts.json")):
            raise ReleaseInputError(
                f"asset filename {name!r} does not belong to a rights-approved dataset"
            )
        accepted.append(name)
    return accepted


def validate_oversized(entries: str | Sequence[str], registry: Registry,
                       *, max_asset_bytes: int = MAX_ASSET_BYTES) -> list[dict[str, Any]]:
    """Validate ``dataset=bytes`` entries for datasets too large for one asset.

    The entry is a *claim* recorded in the index; it never authorises a download
    or an upload. It must therefore be well formed, refer to an approved dataset
    and actually exceed the asset limit.
    """
    if isinstance(entries, str):
        items = entries.split()
    else:
        items = [str(item) for item in entries]
    allowed = allowed_dataset_ids(registry)
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        dataset_id, separator, size = item.partition("=")
        if not separator:
            raise ReleaseInputError(f"oversized entry {item!r} must be dataset=bytes")
        if not DATASET_RE.match(dataset_id):
            raise ReleaseInputError(f"malformed dataset id {dataset_id!r} in oversized entry")
        if dataset_id not in allowed:
            raise ReleaseInputError(f"oversized entry names a dataset that may not be published: {dataset_id}")
        if not size.isdigit():
            raise ReleaseInputError(f"oversized entry {item!r} has a non-numeric byte count")
        value = int(size)
        if value <= max_asset_bytes:
            raise ReleaseInputError(
                f"{dataset_id} is {value} bytes, not above the {max_asset_bytes} byte asset limit; "
                "package it directly instead of declaring it oversized"
            )
        if dataset_id in seen:
            raise ReleaseInputError(f"duplicate oversized entry for {dataset_id}")
        seen.add(dataset_id)
        accepted.append({
            "dataset_id": dataset_id,
            "raw_bytes": value,
            "reason": (
                f"exceeds the {max_asset_bytes} byte asset limit; distribute as multipart packages "
                "or reacquire with `atlas data sync`"
            ),
        })
    return accepted


def build_plan(raw_datasets: str | Sequence[str], tag: str, oversized: str | Sequence[str],
               registry: Registry) -> dict[str, Any]:
    """The single validated plan every later release step reads.

    Downstream steps never re-parse raw workflow input. They read this document,
    so a value that passed validation once cannot be reinterpreted by a shell.
    """
    datasets = validate_dataset_ids(raw_datasets, registry)
    decisions = dataset_decisions(registry)
    return {
        "schema": "atlas.open_data.release_plan.v1",
        "created_at": utcnow(),
        "release_tag": validate_tag(tag),
        "registry_reviewed_at": registry.payload.get("reviewed_at"),
        "asset_limit_bytes": MAX_ASSET_BYTES,
        "datasets": [
            {
                "dataset_id": dataset_id,
                "rights_class": decisions[dataset_id]["rights_class"],
                "rights_reason": decisions[dataset_id]["reason"],
                "title": decisions[dataset_id]["title"],
                "provider": decisions[dataset_id]["provider"],
                "assets": [f"{dataset_id}.tar.zst", f"{dataset_id}.tar.zst.sha256",
                           f"{dataset_id}.index.json"],
            }
            for dataset_id in datasets
        ],
        "oversized": validate_oversized(oversized, registry),
        "policy": (
            "The dataset list, tag and oversized claims were validated against the registry "
            "and a strict grammar. Publication re-validates them and refuses an existing tag."
        ),
    }


# ------------------------------------------------------------------- catalogue IO
def read_release_index(path: str | Path = DEFAULT_INDEX) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReleaseLookupError(f"release index {target} is not valid JSON: {exc}") from exc
    return payload


def write_release_index(payload: Mapping[str, Any], path: str | Path = DEFAULT_INDEX) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def read_downloads(path: str | Path = DEFAULT_DOWNLOADS) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(payload.get("downloads") or [])


def record_download(payload: Mapping[str, Any], path: str | Path = DEFAULT_DOWNLOADS) -> Path:
    """Append an independent-download verification record.

    A record is written only after the streamed bytes hashed to the expected
    digest, so the catalogue can distinguish "an asset exists in a release" from
    "these exact bytes were downloaded and verified somewhere".
    """
    target = Path(path)
    existing = read_downloads(target)
    key = (payload.get("url") or payload.get("asset"), payload.get("sha256"))
    if not any((item.get("url") or item.get("asset"), item.get("sha256")) == key for item in existing):
        existing.append(dict(payload))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"schema": "atlas.open_data.downloads.v1",
                                  "downloads": existing}, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    return target


def write_publication_record(payload: Mapping[str, Any], directory: str | Path = DEFAULT_PUBLICATIONS) -> Path:
    """Preserve a publication attempt, successful or failed, as its own file."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().replace(":", "").replace("-", "")
    status = str(payload.get("status") or "unknown")
    path = target / f"{stamp}-{status}.json"
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------- published availability
def fetch_github_release(repo: str = DEFAULT_REPO, tag: str | None = None, *,
                         token: str | None = None, timeout: float = 20.0) -> dict[str, Any]:
    """Read a published release through the GitHub API (no credentials required).

    Unauthenticated reads work for public repositories. A token is used when the
    caller has one, but it is never required to *verify* a publication, which is
    what makes independent verification possible from a clean machine.
    """
    repo = repo.strip("/")
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
        raise ReleaseLookupError(f"malformed repository {repo!r}")
    if tag:
        validate_tag(tag)
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    else:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=20"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Atlas-Data-Engine/1.0",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ReleaseLookupError(f"GitHub returned {exc.code} for {url}") from exc
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        raise ReleaseLookupError(f"cannot read {url}: {exc}") from exc
    if isinstance(payload, list):
        return {"releases": payload}
    return payload


def published_assets(release: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Normalise GitHub assets into the catalogue's asset shape."""
    if not release:
        return []
    assets = []
    for asset in release.get("assets") or []:
        digest = asset.get("digest") or ""
        assets.append({
            "asset": asset.get("name"),
            "bytes": asset.get("size"),
            "sha256": digest.removeprefix("sha256:") if isinstance(digest, str) else None,
            "url": asset.get("browser_download_url"),
            # Draft release assets are only reachable through the authenticated API
            # endpoint; the byte verifier tries this before the browser URL.
            "api_url": asset.get("url"),
            "state": asset.get("state"),
            "created_at": asset.get("created_at"),
        })
    return assets


# ------------------------------------------------------------------------ catalogue
STATE_ORDER = [
    "discovered",
    "rights_approved",
    "acquired",
    "local_available",
    "packaged",
    "uploaded",
    "download_verified",
    "restored",
    "integrated",
]


def _index_counts(index_db: str | Path | None) -> dict[str, dict[str, int]]:
    if not index_db:
        return {}
    path = Path(index_db)
    if not path.exists():
        return {}
    counts: dict[str, dict[str, int]] = {}
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for dataset_id, records, observations in connection.execute(
                "SELECT dataset_id, records, observations FROM coverage"):
            counts[str(dataset_id)] = {"records": int(records or 0),
                                       "observations": int(observations or 0)}
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return counts


def release_catalog(
    registry: Registry,
    store: SnapshotStore,
    *,
    index_path: str | Path = DEFAULT_INDEX,
    downloads_path: str | Path = DEFAULT_DOWNLOADS,
    release: Mapping[str, Any] | None = None,
    open_data_db: str | Path | None = None,
) -> dict[str, Any]:
    """The authoritative availability catalogue.

    Every rung is derived from an artefact: the registry, a committed manifest,
    bytes that hash correctly, a built package, the GitHub API, a recorded
    independent download, a restored snapshot or the index database. A dataset
    with a hash in Git and no uploaded asset is reported as ``packaged``, never
    as durable.
    """
    from .durable import committed_manifests  # local import: avoids a cycle

    decisions = dataset_decisions(registry)
    manifests = committed_manifests()
    downloads = read_downloads(downloads_path)
    published = published_assets(release)
    counts = _index_counts(open_data_db)
    rows: list[dict[str, Any]] = []
    for dataset in registry:
        dataset_id = dataset.id
        decision = decisions[dataset_id]
        committed = manifests.get(dataset_id, {})
        snapshots = store.list_snapshots(dataset_id)
        local = None
        for snapshot in reversed(snapshots):
            report = store.verify(snapshot, deep=True)
            local = {
                "snapshot_id": snapshot.snapshot_id,
                "status": "verified" if report["ok"] else "corrupt",
                "source_bytes": sum(int(item.get("bytes") or 0) for item in snapshot.files),
                "restored_from": snapshot.manifest.get("restored_from"),
            }
            if report["ok"]:
                break
        assets = [item for item in published
                  if str(item.get("asset") or "").startswith(f"{dataset_id}.")]
        verified_downloads = [item for item in downloads
                              if str(item.get("asset") or item.get("url") or "").split("/")[-1]
                              .startswith(f"{dataset_id}.")]
        row = {
            "dataset_id": dataset_id,
            "title": dataset["title"],
            "provider": dataset.provider,
            "discovered": True,
            "rights_approved": decision["allowed"],
            "rights_class": decision["rights_class"],
            "rights_reason": decision["reason"],
            "acquired_snapshots": sorted(committed),
            "acquired": bool(committed),
            "local_snapshot": local,
            "local_available": bool(local and local["status"] == "verified"),
            "packages_built": [],   # filled from the release index below
            "packages_uploaded": assets,
            "downloads_verified": verified_downloads,
            "restored": bool(local and local.get("restored_from")),
            "integrated_records": counts.get(dataset_id, {}).get("records", 0),
        }
        state = "discovered"
        for candidate, reached in (
            ("rights_approved", row["rights_approved"]),
            ("acquired", row["acquired"]),
            ("local_available", row["local_available"]),
        ):
            if reached:
                state = candidate
        rows.append(row)

    index = read_release_index(index_path)
    by_dataset = {row["dataset_id"]: row for row in rows}
    for asset in index.get("assets") or []:
        row = by_dataset.get(str(asset.get("dataset_id")))
        if row is None:
            continue
        row["packages_built"].append({
            "asset": asset.get("asset"),
            "bytes": asset.get("asset_bytes"),
            "sha256": asset.get("asset_sha256"),
            "snapshot_id": asset.get("snapshot_id"),
            "rights_class": asset.get("rights_class"),
            "rights_source": index.get("rights_source"),
        })
    for row in rows:
        if row["packages_built"]:
            row["state"] = "packaged"
        elif row["local_available"]:
            row["state"] = "local_available"
        elif row["acquired"]:
            row["state"] = "acquired"
        elif row["rights_approved"]:
            row["state"] = "rights_approved"
        else:
            row["state"] = "discovered"
        if row["packages_uploaded"]:
            row["state"] = "uploaded"
        if row["downloads_verified"]:
            row["state"] = "download_verified"
        if row["restored"]:
            row["state"] = "restored"
        if row["integrated_records"]:
            row["state"] = "integrated"

    summary = {state: sum(1 for row in rows if row["state"] == state) for state in STATE_ORDER}
    summary.update({
        "datasets": len(rows),
        "rights_approved_total": sum(1 for row in rows if row["rights_approved"]),
        "durable_snapshots": sum(1 for row in rows if row["local_available"]),
        # `state` is the highest rung reached. `reached` counts each rung from that
        # rung's own evidence, never by position in the ladder: a dataset restored
        # from a local mirror has not therefore been uploaded.
        "reached": {
            "discovered": len(rows),
            "rights_approved": sum(1 for row in rows if row["rights_approved"]),
            "acquired": sum(1 for row in rows if row["acquired"]),
            "local_available": sum(1 for row in rows if row["local_available"]),
            "packaged": sum(1 for row in rows if row["packages_built"]),
            "uploaded": sum(1 for row in rows if row["packages_uploaded"]),
            "download_verified": sum(1 for row in rows if row["downloads_verified"]),
            "restored": sum(1 for row in rows if row["restored"]),
            "integrated": sum(1 for row in rows if row["integrated_records"]),
        },
    })
    return {
        "schema": "atlas.open_data.release_catalog.v1",
        "generated_at": utcnow(),
        "release_tag": index.get("release_tag"),
        "release": {
            "tag": (release or {}).get("tag_name"),
            "url": (release or {}).get("html_url"),
            "draft": (release or {}).get("draft"),
            "published_at": (release or {}).get("published_at"),
            "assets": len(published),
        },
        "states": STATE_ORDER,
        "summary": summary,
        "datasets": rows,
        "distinction": (
            "`packaged` means an asset with that hash was built locally. `uploaded` means the "
            "GitHub API returned it. `download_verified` means those bytes were streamed and "
            "hashed after publication. `restored` means a store holds a snapshot that records "
            "it came from a package. Only the last two are evidence of durability."
        ),
    }


def catalog_table(catalog: Mapping[str, Any]) -> str:
    rows = sorted(catalog.get("datasets") or [], key=lambda row: (STATE_ORDER.index(row["state"]), row["dataset_id"]))
    width = max([len(row["dataset_id"]) for row in rows] + [10])
    lines = []
    for row in rows:
        assets = len(row.get("packages_built") or [])
        uploaded = len(row.get("packages_uploaded") or [])
        verified = len(row.get("downloads_verified") or [])
        lines.append(
            f"{row['state']:<16} {row['dataset_id']:<{width}} rights={'yes' if row['rights_approved'] else 'no':<3} "
            f"local={'yes' if row['local_available'] else 'no':<3} packaged={assets} "
            f"uploaded={uploaded} verified={verified} records={row['integrated_records']}"
        )
    return "\n".join(lines) or "(no registered datasets)"
