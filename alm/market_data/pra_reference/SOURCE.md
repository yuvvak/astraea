# Real PRA-published technical information

Downloaded from the Bank of England's Solvency II technical information page
on 2026-09-09:
<https://www.bankofengland.co.uk/prudential-regulation/key-initiatives/solvency-ii/technical-information>

- `risk-free-curves-31-aug-2026.xlsx`: basic RFR curves, with-VA curves,
  Smith-Wilson extrapolation parameters and pre-shocked curves, by currency.
  <https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/solvency-ii/rfr-releases-2026/risk-free-curves-31-aug-2026.xlsx>
- `risk-free-fs-pod-and-cod-31-aug-2026.xlsx`: Fundamental Spread,
  Probability of Default and Cost of Downgrade, by currency/sector/CQS/maturity.
  <https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/solvency-ii/rfr-releases-2026/risk-free-fs-pod-and-cod-31-aug-2026.xlsx>

Release date: 31 August 2026 data, published 8 September 2026 (the PRA
publishes on or before the 8th working day of the following month, so this
was the most recent release at the time).

Used by `rfr_loader.load_rfr_curve_from_pra_workbook` and
`fs_loader.load_fs_table_from_pra_workbook` as real-schema fixtures (see
`alm/tests/test_market_data_loaders.py`) to prove the loaders against an
actual published file rather than just this project's own documented v1
format. The numbers in these files change every month since they're real
published data, so tests against them should assert plausibility (sane
ranges, expected currencies/sectors present), not exact hand-solved values.
