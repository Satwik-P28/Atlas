# Investment committee brief (ICB) execution

The ICB workflow turns a completed equity analysis into a fixed, reviewable brief. It is an
execution path over the deterministic report; it adds no new valuation mathematics.

## Steps

1. Select an issuer with `valuation_eligibility == "eligible"` and a passing DCF audit. If
   either condition fails, the brief records the refusal and stops at the financial review.
2. Capture `metadata.report_sha256`, the information cutoff and the source revision.
3. Attach the reconciliation checks, the audit verdict, the share-denominator basis and every
   finding to the brief.
4. State the assumptions as assumptions. WACC, terminal growth, margin and tax are not
   presented as observed facts.
5. Record what is unavailable: prices, consensus, guidance, qualitative narrative and any
   market-implied value.
6. Package the analysis so a reviewer can reproduce the numbers from a clean database.

## What the brief must not contain

- A rating, target price or recommendation. Atlas produces none.
- A valuation for JPMorgan, Goldman Sachs or UnitedHealth using the generic DCF.
- A "fair value" claim when the terminal value dominates enterprise value or when the
  denominator is derived.
- Any statement that the research is institutional quality or human-validated.

## Evidence to attach

- Report SHA-256 and package SHA-256.
- The DCF audit table with all eight component checks.
- The findings list, including preserved negative values.
- The missing-concept list and the market-data gap.
- The exact query parameters (`as_of`, `mode`, assumptions).
