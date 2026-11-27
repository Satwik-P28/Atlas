#!/usr/bin/env python3
"""Download allowlisted public snapshots into ignored local storage."""
import argparse
import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/open_data/catalog.json"


def download(url, dest, limit, agent, opener=urlopen):
    h = hashlib.sha256()
    size = 0
    with opener(Request(url, headers={"User-Agent": agent}), timeout=120) as response:
        if urlsplit(response.geturl()).scheme != "https" or urlsplit(response.geturl()).hostname != urlsplit(url).hostname:
            raise ValueError("Unexpected redirect: " + response.geturl())
        with dest.open("xb") as out:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Download exceeds configured byte limit")
                h.update(chunk)
                out.write(chunk)
    if not size:
        raise ValueError("Empty download")
    return {"url": url, "file": dest.name, "bytes": size, "sha256": h.hexdigest()}


def fetch(dataset, root, agent, opener=urlopen):
    parent = root / dataset["id"]
    parent.mkdir(parents=True, exist_ok=True)
    start = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(dir=parent, prefix=".partial-") as tmp:
        stage = Path(tmp)
        files = []
        if dataset["kind"] == "fiscal_api":
            page, expected, total, count, remaining = 1, None, None, 0, dataset["max_bytes"]
            while True:
                url = dataset["url"] + "?" + urlencode({"sort": "record_date", "page[number]": page, "page[size]": 1000})
                path = stage / f"page-{page:05d}.json"
                entry = download(url, path, remaining, agent, opener)
                remaining -= entry["bytes"]
                payload = json.loads(path.read_bytes())
                rows = payload["data"]
                meta = payload["meta"]
                pages = int(meta["total-pages"])
                row_total = int(meta["total-count"])
                if expected is None:
                    expected, total = pages, row_total
                    if not 1 <= expected <= 10000 or total < 1:
                        raise ValueError("Unexpected pagination size")
                if pages != expected or row_total != total or not isinstance(rows, list) or not rows:
                    raise ValueError("Inconsistent or empty page")
                count += len(rows)
                files.append(entry)
                if page == expected:
                    if count != total:
                        raise ValueError("Incomplete snapshot")
                    break
                page += 1
                time.sleep(0.25)
        else:
            path = stage / dataset["filename"]
            files.append(download(dataset["url"], path, dataset["max_bytes"], agent, opener))
            if dataset["kind"] == "zip":
                import zipfile
                with zipfile.ZipFile(path) as archive:
                    if not archive.infolist():
                        raise ValueError("Empty ZIP")
            elif dataset["kind"] == "json":
                json.loads(path.read_bytes())
            elif dataset["kind"] in {"tsv", "csv"}:
                import csv
                delimiter = "\t" if dataset["kind"] == "tsv" else ","
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = csv.reader(stream, delimiter=delimiter)
                    header = next(rows, [])
                    if len(header) < 2 or not next(rows, []):
                        raise ValueError("Expected tabular data")
            else:
                raise ValueError("Unknown dataset kind")
        manifest = {"dataset": dataset, "started_at": start.isoformat(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "snapshot_semantics": "current provider snapshot; historical availability not inferred",
                    "files": files}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        final = parent / start.strftime("%Y%m%dT%H%M%S.%fZ")
        if final.exists():
            raise FileExistsError(final)
        os.rename(stage, final)
        return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*", help="Dataset IDs; omit to list")
    parser.add_argument("--all", action="store_true", help="Download every allowlisted dataset; requires substantial disk space")
    parser.add_argument("--contact", help="Real name or organization and contact email for agency access")
    args = parser.parse_args()
    datasets = {d["id"]: d for d in json.loads(CATALOG.read_text())["datasets"]}
    if not args.ids and not args.all:
        for key, d in datasets.items():
            print(key, d["provider"], d["rights"])
        return
    if args.all and args.ids:
        parser.error("Use IDs or --all, not both")
    if not args.contact or "@" not in args.contact or "\n" in args.contact or "\r" in args.contact:
        parser.error("A real contact email is required for downloads")
    ids = list(datasets) if args.all else args.ids
    unknown = set(ids) - datasets.keys()
    if unknown:
        parser.error("Unknown or unapproved dataset: " + ", ".join(sorted(unknown)))
    for key in dict.fromkeys(ids):
        print(fetch(datasets[key], ROOT / "var/open_data", "Atlas research " + args.contact))
        time.sleep(0.25)


if __name__ == "__main__":
    main()
