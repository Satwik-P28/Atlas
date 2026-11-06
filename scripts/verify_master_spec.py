#!/usr/bin/env python
"""Verify the supplied master specification against its declared size and hash.

The gate is intentionally strict: a truncated, regenerated or edited document fails.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "ATLAS_MASTER_SPEC.md"
EXPECTED_BYTES = 155_419
EXPECTED_SHA256 = "e54c59737f48a2faf6e62bddf76f0292efd634cda03bc7a6a5c2aed4ed4ba5c9"


def main() -> int:
    if not SPEC.exists():
        print(f"BLOCKED: {SPEC.name} is not present; expected {EXPECTED_BYTES} bytes, "
              f"sha256 {EXPECTED_SHA256}")
        return 1
    payload = SPEC.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    size_ok = len(payload) == EXPECTED_BYTES
    hash_ok = digest == EXPECTED_SHA256
    print(f"size={len(payload)} expected={EXPECTED_BYTES} ok={size_ok}")
    print(f"sha256={digest} ok={hash_ok}")
    if not (size_ok and hash_ok):
        print("BLOCKED: supplied file does not match the declared master specification")
        return 1
    print("VERIFIED: master specification matches size and SHA-256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
