# Real PRA-published technical information

Downloaded from the Bank of England's Solvency II technical information
page during this session (2026-09-09):
<https://www.bankofengland.co.uk/prudential-regulation/key-initiatives/solvency-ii/technical-information>

- `risk-free-curves-31-aug-2026.xlsx` -- basic RFR curves, with-VA curves,
  Smith-Wilson extrapolation parameters and pre-shocked curves, by currency.
  <https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/solvency-ii/rfr-releases-2026/risk-free-curves-31-aug-2026.xlsx>
- `risk-free-fs-pod-and-cod-31-aug-2026.xlsx` -- Fundamental Spread,
  Probability of Default and Cost of Downgrade, by currency/sector/CQS/maturity.
  <https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/solvency-ii/rfr-releases-2026/risk-free-fs-pod-and-cod-31-aug-2026.xlsx>

Release date: 31 August 2026 data, published 8 September 2026 (the most
recent monthly release available at download time -- the PRA publishes on
or before the 8th working day of the following month).

These are used by `alm/market_data/rfr_loader.py`'s
`load_rfr_curve_from_pra_workbook` and `alm/market_data/fs_loader.py`'s
`load_fs_table_from_pra_workbook` as real-schema fixtures (see
`alm/tests/test_market_data_loaders.py`), proving the loaders against an
actual published file rather than only this project's own documented v1
long format. Since these are real published files, the numbers inside them
change every month -- do not write tests that assert exact hand-solved
values against them; assert plausibility (sane ranges, expected currencies/
sectors present) instead.
