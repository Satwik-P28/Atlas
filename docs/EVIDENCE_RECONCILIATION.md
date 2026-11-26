# Evidence reconciliation

Status: deterministic conflict preservation is implemented for the station disagreement.
News de-duplication, general entity resolution and LLM extraction are not implemented.

## Flow

```
source registry
  → deterministic CSV parse
  → time/unit normalization
  → observation record with provenance
  → claim with stable subject/predicate/source identity
  → conflict detection by matching subject key
  → dependent analyses marked stale
  → reviewer-visible conflict; no automatic winner
```

## Implemented operations

* Source collection from documented public archives.
* Retrieval and observation timestamp normalization.
* Duplicate observation control by stable series/day/vintage/revision identity.
* Entity records with canonical keys and geography.
* Claim extraction for daily maximum temperature and the hypothesis edge.
* Contradiction detection for same-subject, same-date, same-unit station claims.
* Evidence linkage through observation, claim and source IDs.
* Review state `unresolved`; resolution is null.
* Source-quality, representativeness and vintage warnings.
* Correction via a revision record that retains the old observation.

## The flagship conflict

On 2023-06-30 the two official Dallas stations report different daily maximum temperatures:

| Station | Claim value | Epistemic status | Source |
|---|---:|---|---|
| Dallas Redbird `USW00003971` | 32.8 °C | observed | `noaa-ghcn` |
| Dallas/Fort Worth `USW00013960` | 35.6 °C | observed | `noaa-ghcn` |

The conflict record preserves both claims, both observation IDs, both timestamps, the
subject, the unit and the difference. It reports:
`two observed station measurements disagree for the same metro-area subject`.
The interpretation is station representativeness, not a finding that one instrument is wrong.

Detecting this conflict does not modify the primary weather series. The primary station is a
declared design choice with a stated limitation; the comparison station is independent. The
UI labels this disagreement and does not select a winner.

## Correction behavior

`POST /api/economic/observations/{id}/revise` inserts a new observation with a higher revision
sequence and `supersedes` pointing at the old row. The old row is unchanged. All analyses whose
dependency index includes the old observation are marked `stale`, an alert is recorded, and
saved applications keep their original result until the user reruns them.

The UI correction drill uses 35.7 °C and a reason string. It does not delete or replace source
history and does not automatically retrain.

## Duplicate-source policy

A claim is keyed by subject, predicate, value, unit and source identity. Repeated copies from
the same source would not create independent evidence. The current implementation does not
cluster syndicated articles because no article ingestion exists. News mention counts are not
used as severity or confirmation.

## Limits

* No fuzzy entity resolution.
* No general document/event parser.
* No independent adjudication workflow or reviewer identity.
* No cross-source weighting model.
* No automatic promotion of a resolved value; resolution remains an explicit future action.
* Formal conflict types are limited to numeric same-subject measurements and hypothesis edges.

## Rights

Both sources are U.S. Government public-domain works. URLs, provider identity and file hashes
are retained. The derived conflict and research outputs retain their source attribution.
