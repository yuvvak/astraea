# Astraea

Astraea is an independent ALM engine for UK annuity business written under the
Matching Adjustment (MA). It models MA-eligible liabilities and their backing
assets, and reproduces the calculations a firm's actuarial function has to
run: the two-AER MA calculation, all five PRA matching tests, hypothecation,
Risk Margin, and a Standard Formula SCR.

The idea is to run it alongside a firm's existing process (in-house, Prophet +
R, or a vendor system) as a second, independently-built calculation to check
the firm's own numbers against, not to replace that process. A firm's
reserving data is sensitive enough that most insurers won't put it in a
third-party cloud without a lot of due diligence, so it's built to be
self-hosted and run inside the customer's own infrastructure under a license.

Package/CLI names stayed as `alm` internally; "Astraea" is just the
product-facing name.

## Running it

```bash
python -m venv .venv && .venv/Scripts/pip install pydantic pandas numpy scipy openpyxl pytest
.venv/Scripts/python -m pytest alm/tests/ -v
```

The test suite is the main way to sanity-check the engine: it's checked
against hand-worked and closed-form results, not just internal consistency.

As an installable package, with the licensing CLI:

```bash
pip install -e .
alm-license generate-keypair --out-dir ./keys
alm-license issue --private-key ./keys/private_key.pem --customer "Example Ltd" --tier professional --expiry 2027-09-08 --out license.txt
alm-license verify --public-key ./keys/public_key.pem license.txt
```

## What's in it

**`alm/contracts/`** - the shared data model: curves, cash flow vectors,
asset types (bonds, cash, amortizing loans, swaps, reinsurance
recoverables, fund holdings), model point attributes. Everything else is
built on top of this.

**`alm/ma/`** - the MA calculation itself: the two-AER formula, funded spread
aggregation, hypothecation across Components A/B/C, the sub-investment-grade
cap, the HP benefit cap, and MAIA tracking.

**`alm/tests_pra/`** - the five PRA matching tests (Accumulated Cash Flow
Shortfall, VaR, Notional Swap, MA Loss Test, Modified Accumulated Shortfall),
run against a small portfolio sized to actually exercise all three
hypothecation components.

**`alm/stresses/`** - a scenario runner that takes a stress spec, shocks the
curve/FS table/liability cash flows, re-hypothecates, and reports the impact
on MA and own funds, including whether Test 1 still passes afterwards.

**`alm/rm/`** - Risk Margin (cost of capital 4%, life taper with a 0.25
floor).

**`alm/scr/`** - the Standard Formula SCR: spread, currency, interest rate
and concentration risk aggregated into market risk, plus longevity,
counterparty default, and operational risk. Calibration (shock sizes,
correlation matrices) is pulled from the real PRA Rulebook / Solvency II
Annex IV figures rather than illustrative placeholders, with one exception:
counterparty default is still a flat placeholder charge, because the real
Article 199 formula is involved enough that I'd rather leave it honestly
unfinished than risk getting a capital number subtly wrong.

**`alm/capital/`** - Basic Own Funds (assets minus technical provisions) and
the resulting SCR coverage ratio, the headline number insurers actually
publish. It stops at "basic" rather than "eligible" own funds since there's
no modelling of a firm's actual capital structure here.

**`alm/market_data/`** - loaders for RFR curves and FS tables, including
adapters that parse the real Bank of England Solvency II technical
information workbooks (checked into `alm/market_data/pra_reference/`).

**`alm/prophet_io/`** - an adapter for Prophet extracts, built against a
documented v1 schema since no real sample extract was available.

**`alm/validation/reconciliation.py`** - the core of the product: compares a
customer's own supplied figures (MA, BEL, FS rate, RM, SCR, Test 1 ratio)
against this engine's independent recalculation, and flags each as
not-supplied, immaterial, watch or material. Tested against a deliberately
injected version of one of the most common real-world MA errors (forgetting
to net funded spread out of the rate) to confirm it actually gets flagged.

**`alm/licensing/`** - self-hosted license entitlement, signed with Ed25519.
`issue_license` and `generate_keypair` are vendor-side only; customers only
ever hold `verify_license` and a public key, which is proven insufficient to
forge a license.

**`alm/config/`** - `FirmConfig`: valuation date, currencies, SCR mode,
hypothecation algorithm, and reconciliation tolerances, loadable from a JSON
file per firm.

## Known gaps

- Counterparty default SCR uses an illustrative flat charge, not the full
  Article 199 Type 1/2 formula.
- No real regulator-submittable filing format (QRT/XBRL); reporting output
  is a structured JSON object and a markdown narrative.
- The inflation leg of PRA Test 2's VaR uses an illustrative shock size -
  I couldn't find a published PRA/EIOPA table to calibrate it against.
- `FirmConfig.matching_bucket_frequency` is informational only for now;
  cash flow models are annual throughout regardless of what it's set to.
- No real UK insurer's policy-level data is available to this project, so
  the engine has never been run against one. As a rough sanity check, the
  SCR composition on the toy portfolio was compared against Rothesay Life's
  published FY2025 figures (see the git history around that commit) - the
  split doesn't match, mostly because Rothesay reinsures most of its
  longevity risk and runs a PRA-approved internal model rather than the
  standard formula. Directional check, not a validation.

## A few design decisions worth knowing before extending this

- Cash flow sign is carried by `CashFlowVector.direction`
  (`liability_outgo` / `asset_income`), not by the sign of `amount`, which
  is always a positive magnitude. `net_by_time` does the actual netting.
- Curve interpolation is linear on the zero rate between PRA term points,
  flat beyond the ends.
- MA is computed cash-flow-level (`MA = r1 - r2 - FS_rate`), not via a
  weighted-average-life shortcut.
- Gilts get FS = 0 by convention rather than a rating/sector lookup.
- Hypothecation across Components A/B/C is PV-fraction based rather than a
  single scalar per position, because a scalar bounded by one oversized
  cash flow bucket would zero out an entire position's assignment.
