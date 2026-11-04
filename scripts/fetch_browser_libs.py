"""Fetch the shared libraries Chromium needs, without root.

This workspace has no sudo and no writable dpkg state, so Playwright's
`install-deps` cannot run. Instead we read Ubuntu's package index, download the
missing library packages and unpack them into a local sysroot that only the browser
process sees through LD_LIBRARY_PATH. Nothing outside `.pwlibs/` is modified.

Usage:
    .venv/bin/python scripts/fetch_browser_libs.py
"""

from __future__ import annotations

import gzip
import io
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSROOT = ROOT / ".pwlibs" / "sysroot"
CACHE = ROOT / ".pwlibs" / "debs"
MIRROR = "http://archive.ubuntu.com/ubuntu"
SUITES = ("noble", "noble-updates")
COMPONENTS = ("main", "universe")

WANTED = [
    "libnspr4",
    "libnss3",
    "libasound2t64",
    "libatk1.0-0t64",
    "libatk-bridge2.0-0t64",
    "libatspi2.0-0t64",
    "libxcomposite1",
    "libxdamage1",
    "libxfixes3",
    "libxrandr2",
    "libxkbcommon0",
    "fontconfig-config",
    "libfontconfig1",
    "fonts-dejavu-core",
]


def installed() -> set[str]:
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Package}\n"], capture_output=True, text=True, check=False
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def load_index() -> dict[str, dict[str, str]]:
    packages: dict[str, dict[str, str]] = {}
    for suite in SUITES:
        for component in COMPONENTS:
            url = f"{MIRROR}/dists/{suite}/{component}/binary-amd64/Packages.gz"
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    raw = gzip.decompress(response.read())
            except Exception as error:  # noqa: BLE001 - best effort over several suites
                print(f"  skip {suite}/{component}: {error}")
                continue
            for stanza in raw.decode("utf-8", "replace").split("\n\n"):
                fields: dict[str, str] = {}
                for line in stanza.splitlines():
                    if line.startswith(" ") or ":" not in line:
                        continue
                    key, _, value = line.partition(":")
                    fields[key.strip()] = value.strip()
                name = fields.get("Package")
                if name and name not in packages:
                    packages[name] = fields
            print(f"  index {suite}/{component}: {len(packages)} packages known")
    return packages


def dependencies(stanza: dict[str, str]) -> list[str]:
    names: list[str] = []
    for field in ("Depends", "Pre-Depends"):
        for clause in stanza.get(field, "").split(","):
            clause = clause.strip()
            if not clause:
                continue
            alternative = clause.split("|")[0].strip()
            name = alternative.split(" ")[0].split("(")[0].strip()
            name = name.split(":")[0]
            if name:
                names.append(name)
    return names


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    SYSROOT.mkdir(parents=True, exist_ok=True)
    present = installed()
    print("reading Ubuntu package index…")
    index = load_index()

    queue = list(WANTED)
    resolved: set[str] = set()
    downloaded: list[Path] = []
    while queue:
        name = queue.pop(0)
        if name in resolved or name in present:
            continue
        stanza = index.get(name)
        if not stanza:
            print(f"  warning: no package named {name}")
            continue
        resolved.add(name)
        filename = stanza.get("Filename")
        if not filename:
            continue
        target = CACHE / Path(filename).name
        if not target.exists():
            url = f"{MIRROR}/{filename}"
            print(f"  fetch {name} ({stanza.get('Version')})")
            with urllib.request.urlopen(url, timeout=120) as response:
                target.write_bytes(response.read())
        downloaded.append(target)
        queue.extend(dependencies(stanza))

    for deb in downloaded:
        subprocess.run(["dpkg-deb", "-x", str(deb), str(SYSROOT)], check=True)
    print(f"unpacked {len(downloaded)} packages into {SYSROOT.relative_to(ROOT)}")
    libdirs = sorted({path.parent for path in SYSROOT.rglob("*.so*")})
    print("LD_LIBRARY_PATH=" + ":".join(str(path) for path in libdirs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
