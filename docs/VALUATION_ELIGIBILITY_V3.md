# Valuation eligibility v3

The six states are unchanged: unsupported, insufficient source coverage, methodologically
eligible, arithmetically verified, economically reviewed, independently benchmarked.

v3 adds:

- per-method contracts (`METHOD_CONTRACTS`) with required inputs, required evidence and
  prohibited business models;
- declared but unimplemented REIT FFO/AFFO and property NOI methods, which remain unsupported;
- entity reconciliation, which downgrades a contract when parent and subsidiary evidence is
  incompatible;
- explicit evidence gates instead of a single concealed quality score.

Execution still stops at `arithmetically_verified`. No economic review or external benchmark
is recorded, so no institution model is promoted further.
