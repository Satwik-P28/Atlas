# Regulatory fixtures

## FDIC BankFind Call Reports

`fdic_628_jpmorgan_chase_bank_na.json` and
`fdic_33124_goldman_sachs_bank_usa.json` are public-domain subsidiary Call Report
payloads. They describe insured depositories, not the parent holding companies.

## FFIEC FR Y-9C

`BHCF20241231.ZIP` is the official FFIEC National Information Center quarterly holding
company archive for 2024-12-31.

- Downloaded from the published NIC Financial Data Download page:
  <https://www.ffiec.gov/npw/FinancialReport/FinancialDataDownload?selectedYear=2024>
- Archive: `BHCF20241231.ZIP`
- Size: 1,509,964 bytes
- SHA-256: `65b6479f0b0bc191e57cd2a446cbe31cbcaa3131bf6a1bbdbe4df259f6c89a4b`
- Member: `BHCF20241231.txt` (11,544,617 bytes, caret-delimited, CRLF)
- Retrieved: 2026-11-06

`Financial_Download_Dictionary.xlsx` is the official FFIEC MDRM dictionary linked from
the same page (170,487 bytes; SHA-256
`26c40652a520826167108064db90e329f5cf4c725cb1017599152781ec62188a`).

The archive contains 3,806 holding-company rows and 2,224 columns. The adapter stores
only explicitly mapped FR Y-9C MDRM items for the declared top-tier RSSD. The bulk
archive carries no historical publication timestamp or vintage; Atlas records that
absence and does not claim point-in-time regulatory reconstruction from it.

The archive is retained only because it is a U.S. federal government public dataset.
The parser never downloads data at runtime and never mixes FR Y-9C with FR Y-9LP, the
FDIC Call Report or consolidated SEC facts.
