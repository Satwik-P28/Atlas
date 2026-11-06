# Financial entity resolution

SEC and regulatory reports use different legal entities:

- `JPMorgan Chase & Co.` (CIK 19617) is the consolidated 10-K registrant.
- `JPMorgan Chase Bank, N.A.` (CERT 628) is an insured depository subsidiary.
- `The Goldman Sachs Group, Inc.` (CIK 886982) is the consolidated registrant.
- `Goldman Sachs Bank USA` (CERT 33124) is an insured depository subsidiary.
- `UnitedHealth Group` (CIK 731766) is a consolidated insurer/services registrant with no
  mapped bank subsidiary and no joined CMS plan data.

The consolidated parent supplies equity, earnings and the share count. The subsidiary
supplies Call Report capital, credit and margin evidence. `assert_comparable` rejects mixed
consolidation bases and mixed reporting periods. Subsidiary equity is never added to parent
equity and never divided by parent shares.
