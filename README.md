# Astraea: UK MA ALM Engine (v1, checkpoint 15: real PRA Rulebook SCR calibration across the board, firm config)

**Astraea** is the product name for this engine (goddess of justice and
precision -- fitting for a tool built to independently verify a firm's own
numbers). The Python package and CLI (`alm`, `alm-license`) keep their
existing internal names; "Astraea" is the product/company-facing name used
in documentation, the CV/portfolio copy and the results snapshot, not a
rename of the codebase itself.

Single platform modelling MA-eligible UK annuity liabilities (fed from FIS
Prophet) and the assets, MA, PRA matching tests, stresses, Risk Margin and
SCR that currently live in a separate R codebase. See project brief for the
full regulatory scope (IRPR regs 4-6, PRA Rulebook MA Part, SS7/18, SS8/18).

Run it:

```bash
python -m venv .venv && .venv/Scripts/pip install pydantic pandas numpy scipy openpyxl pytest
.venv/Scripts/python -m pytest alm/tests/ -v
```

146/146 tests pass, all against independent hand/closed-form cross-checks or
explicitly-reasoned expected outcomes, not just internal consistency.

Install as a real package (not just "run from checkout"):

```bash
pip install -e .
alm-license generate-keypair --out-dir ./keys
alm-license issue --private-key ./keys/private_key.pem --customer "Example Ltd" --tier professional --expiry 2027-09-08 --out license.txt
alm-license verify --public-key ./keys/public_key.pem license.txt
```

## Product direction

This engine is being positioned as a self-hosted **independent validation
layer**: it runs alongside a firm's existing MA/SCR process (in-house,
Prophet+R, or a vendor system) rather than replacing it, reconciling the
firm's own headline figures against an independent recalculation and
flagging material divergence. Self-hosted, not a hosted SaaS: live
reserving data is sensitive enough that most insurers won't put it in a
third-party cloud without extensive due diligence, so the customer runs
this inside their own infrastructure on a license.

- **`alm/validation/reconciliation.py`**: the core product mechanic.
  Compares customer-supplied figures (MA, BEL, FS rate, RM, SCR, Test 1
  ratio; every field optional) against this engine's own independent
  calculation on the same portfolio, flags each as not-supplied,
  immaterial, watch or material against a relative tolerance (2%
  material / 0.5% watch by default, falling back to an absolute
  tolerance when the independent value is ~0). Verified against a
  deliberately-injected version of the single most common real-world MA
  error (forgetting to net FS out of the rate), which the reconciliation
  correctly flags material.
- **Real-firm benchmark**: no real UK insurer's underlying policy data
  is available to this project, so this engine hasn't been run against
  one. As a substitute sanity check, Astraea's own Standard Formula SCR
  composition (golden-toy portfolio) is compared against Rothesay Life
  Plc's real published FY2025 SCR composition (Annual Report &amp;
  Accounts 2025, Note F.1) -- the split differs (46/50/1/2% vs
  Rothesay's disclosed 80/10/6/4%), and the note explains why honestly:
  Rothesay reinsures 91% of its longevity risk, stripping most of the
  insurance-risk component out of its SCR, while the golden-toy portfolio
  carries its longevity exposure unreinsured. Also flags plainly that
  Rothesay uses a PRA-approved Full Internal Model, not the Standard
  Formula this engine implements, so this is a directional check, not a
  methodology match.
- **`alm/licensing/entitlement.py`**: self-hosted license entitlement.
  A signed token (customer, expiry, tier, legal-entity limit) checked
  locally at startup, since there's no vendor-side account to gate access
  for software that runs inside the customer's own environment. Signs
  with **Ed25519** (asymmetric): `issue_license`/`generate_keypair` are
  vendor-side only and never ship; `verify_license` and the public key
  are what the customer's installed package holds, and holding only that
  is proven insufficient to forge a new license (a real test, not just an
  assertion: fabricating a payload and reusing unrelated signature bytes
  is correctly rejected). Three tiers (starter/professional/enterprise)
  gate feature access. `alm/cli.py` (`alm-license` once installed) is the
  vendor-side and customer-side command-line tool for all three
  operations.
- **`alm/market_data/`**: RFR curve and FS table loaders from XLSX
  (`rfr_loader.py`, `fs_loader.py`), replacing the "always built directly
  in code" gap from earlier checkpoints. Each defines its own simple,
  documented long-format schema (one row per currency/term, or per
  currency/rating/sector/term) for callers that don't want to deal with the
  PRA's actual wide, multi-tab layout -- the same documented-v1-default
  pattern as the Prophet adapter. Proven with more than a round-trip: a
  curve and FS table loaded from an XLSX file in that documented format (not
  built in code) reproduce the golden Scenario B MA figure,
  135.4463645158851bp, to nine decimal places. **Now also proven against a
  REAL published file**: `load_rfr_curve_from_pra_workbook` /
  `load_fs_table_from_pra_workbook` parse the actual Bank of England
  Solvency II technical information workbooks (checked into
  `alm/market_data/pra_reference/`, see `SOURCE.md` there for the release
  date/URL), locating each currency's column / each sector's FS-and-CoD
  block by header text search rather than a hardcoded index.

## What's built

- **`alm/contracts/`**: shared pydantic contracts: `Curve` (RFR term
  structure), `CashFlow`/`CashFlowVector` (the one CF representation used by
  liabilities, assets, MA, tests and stresses), `FSTable`/`FSEntry`/
  `RatingNotch`/`AssetSector`, `ModelPointAttributes`/`ProductCode`, a
  `Bond`/`Cash`/`AmortizingLoan`/`InterestRateSwap`/`AssetPosition` (Bond
  doubles as an index-linked gilt via `inflation_linked`/
  `assumed_inflation_rate`; AmortizingLoan covers infra debt, ERM
  restructured notes, project finance and CRE loans in one instrument,
  since they share the same interest-plus-scheduled-principal cash flow
  shape; InterestRateSwap and InflationSwap project and freeze expected
  net cash flows at construction (from the curve's own forward rates, or
  a flat inflation assumption respectively), and CAN have negative period
  cash flows and negative market value, a deliberate narrow exception to
  this module's positive-magnitude convention -- see InterestRateSwap's
  docstring; ReinsuranceRecoverable, whose funded collateral reduces net
  counterparty exposure but is never netted into market value -- brief:
  "do not treat FundedRe collateral as automatically MA-eligible"; and
  FundHolding, expanded to its constituents for SF SCR -- see
  `scr.look_through`), a minimal `LevelAnnuityCohort`.
- **`alm/ma/`**: the two-AER MA calculation (`engine.py`, `two_aer.py`),
  FS aggregation (`fs_rate.py`), Component A/B/C hypothecation
  (`hypothecation.py`, greedy nearest-maturity per-bucket waterfall: the
  confirmed v1 default; derivatives are excluded from Component A's
  literal cash-flow-bucket replication but their MV, negative or positive,
  flows correctly through Component B/C -- see "things that looked like
  bugs" below for two real fixes made while wiring this in), a standalone
  HP instrument (`hp_instrument.py`)
  for Tests 4/5, the SIG cap (`sig_cap.py`: MA on sub-IG assets capped at
  the same rate an IG asset would earn, by lifting FS), the HP MA
  benefit cap (`hp_cap.py`: aggregate HP MA benefit <= 10% of total), and
  MAIA tracking (`maia.py`: 24-month regularisation clock, exposure limit
  min(5% of BEL net of RI, GBP 2bn) or a tighter firm limit), and FS
  additions (`fs_additions.py`: named attestation/structure/construction/
  prepayment/HP add-ons to the base FS rate, kept separately reportable
  rather than folded silently into the blended rate, since the MALIR pack
  needs to itemise them).
- **`alm/stresses/scenario_loader.py`**: load/save `StressSpec` lists as
  JSON scenario files (deliverable: "Combined LIST-style and firm ORSA
  scenarios via scenario files"); a malformed file fails loudly via
  pydantic validation rather than silently producing a no-op stress.
  **`runner.py`**'s `reproject_swaps` rebuilds any `InterestRateSwap`
  position from the stressed curve's own forward rates before pricing the
  stressed leg, rather than just re-discounting its frozen construction-
  time cash flows at the new curve -- the difference is large (roughly
  doubles the swap's MV under a -100bp golden-example shock) because a
  swap's floating leg genuinely responds to a rate move, not just its
  discount factor. `InflationSwap` has no curve-implied forward rate to
  reproject from (its flat assumption is exogenous), so it isn't covered
  by this and stays frozen under every stress.
- **`alm/liabilities/eligibility.py`**: the MA eligibility gate (fails
  closed on any unrecognised or disqualified product; every rule cites its
  MA/IRPR paragraph). **`eligibility_matrix.py`**: generates
  `ELIGIBILITY_MATRIX.md` (deliverable 2) by actually running every
  product x feature scenario through the real gate, so the doc can never
  drift from the code; a regression test fails if the checked-in file goes
  stale. Building this matrix caught a real gap (see "things that looked
  like bugs" below). **`mortality_stress_test.py`**: the MA 2.2(3)/2.4
  eligibility gate (mortality risk allowed only if a prescribed stress
  does not raise BEL more than 5%); stresses by extending the cash flow
  stream one period at the final period's amount, not a flat percentage
  scale, so the result actually depends on the liability's duration and
  shape rather than being tautological.
- **`alm/prophet_io/`**: the Prophet extract adapter: documented CSV
  schema (`extract_schema.py`, deliverable 10: no real sample extract
  supplied yet, this is a v1 default isolated behind one file), loader +
  eligibility gate + netting (`adapter.py`).
- **`alm/tests_pra/`**: all five PRA matching tests:
  - **Test 1** (Accumulated Cash Flow Shortfall) and **Test 3** (Notional
    Swap), run on a 3-asset portfolio (5y gilt £300k + 10y A2 corporate
    £600k, £900k total vs BEL £811,089.58: sized to exercise Component A,
    B *and* C). Test 1 correctly **fails** here (68% vs 3% threshold): A+B
    is PV-sufficient but the two bullet/coupon instruments' cash flow
    *shape* doesn't match the smooth annuity liability: exactly the
    mismatch Test 1 exists to catch, independent of PV adequacy.
  - **Test 2** (99.5th percentile 1Y VaR): interest-rate/inflation/currency
    legs on Component A+B market value. The interest-rate and currency legs
    now reuse the real PRA Rulebook Standard Formula calibration (3D5/3D6
    maturity-banded rate shock, 3D32 25% FX shock), a defensible, explicit
    choice since SS7/18 doesn't publish a separate Test-2-specific table.
    The inflation leg's 100bp shock is still an **illustrative placeholder**:
    no published PRA/EIOPA inflation shock table was found; swap
    `var_test.ShockSpec.inflation_shock` when the real one is available.
  - **Test 4** (MA Loss Test, HP) and **Test 5** (Modified Accumulated
    Shortfall, HP), on a synthetic HP bond (10y expected, 8-13y permitted
    repayment bounds). Test 4 isolates the *asset's own* achievable yield
    erosion from forced early reinvestment at a prudent (spread-limited)
    rate, and subtracts that from the MA rate: see `hp_loss_test.py`
    docstring for why perturbing market value directly (an earlier draft)
    gets the sign backwards in this engine.
- **`alm/stresses/`**: a scenario runner (`StressSpec` → shocked curve/FS
  table/liability CFs → full re-hypothecation → recomputed MA → re-run
  Test 1 → own-funds impact), explicitly reporting Test 1 pass/fail
  before/after rather than assuming MA survives a stress unexamined.
- **`alm/rm/`**: Risk Margin: CoC=4%, life taper λ=0.9 floor 0.25,
  discounted on the basic RFR curve; a standard-annuity BEL-runoff
  approximation for SCR(t) when a full projected path isn't supplied.
- **`alm/scr/`**: full Standard Formula SCR, notional/standalone for the MA
  portfolio: spread, currency, interest rate and concentration (market
  risk, aggregated via a market correlation matrix into `market_scr`),
  longevity (life risk), counterparty default (cash/deposit exposure only,
  no reinsurance/derivative counterparties modeled yet), and operational
  risk. Spread (3D17, by credit quality step and the position's own
  Macaulay duration), currency (3D32, 25%), interest rate (3D5/3D6,
  maturity-banded, not a parallel shift), market risk concentrations
  (3D26-3D31, by credit quality step, government positions excluded per
  3D26.4), operational risk (Article 204: 0.45% of life technical
  provisions, capped at 30% of BSCR) and every correlation parameter used
  (both the market sub-module matrix and the top-level BSCR matrix) are now
  the REAL PRA Rulebook / Solvency II Annex IV figures -- see
  `alm/pra_calibration.py` and `alm/scr/standard_formula.py`, verified
  against prarulebook.co.uk and cross-checked against independent sources.
  The market correlation matrix is genuinely conditional, not a fixed
  table: the interest-rate-vs-spread correlation is 0 or 0.5 depending on
  whether the 3D5 rise or 3D6 fall shock actually produced the larger loss
  for that portfolio (`InterestRateScrResult.binding_direction`), matching
  Annex IV's CorrUp/CorrDown distinction. Only counterparty default remains
  an ILLUSTRATIVE PLACEHOLDER: the real Article 199 Type 1/Type 2 formula
  (loss-given-default, PD-by-rating, and a piecewise variance-of-losses
  aggregation) is substantially more involved than every other sub-module
  here, and was deliberately left unimplemented rather than risk a subtly
  wrong regulatory capital formula. `market_scr` + `life` + `counterparty`
  are aggregated into BSCR via the top-level correlation matrix
  (`scr/correlation.py`'s generic `aggregate_via_correlation`, which the
  old 2-variable spread/longevity formula is now a special case of, with
  no change to its result), then `operational` is added and an optional
  `lac_dt` subtracted, floored at zero. `compute_map_standard_formula_scr`
  (spread + longevity only) is kept unchanged for backward compatibility;
  `compute_full_standard_formula_scr` is the complete version.
  Counterparty default prices cash/deposit exposure, in-the-money
  `InterestRateSwap` exposure, and net (collateral-adjusted)
  `ReinsuranceRecoverable` exposure (out-of-the-money swaps and fully
  collateralized reinsurance both correctly contribute nothing).
  `compute_full_standard_formula_scr` expands any `FundHolding` position
  into its constituents (`look_through.py`) before every sub-module runs,
  so a fund's hidden currency/credit exposure is priced at the constituent
  level, not hidden behind one opaque MV.
  **`internal_model.py`**: the SS8/18
  internal-model interface, scoped per the brief ("do not build a full
  economic-scenario generator in v1; define the contract and a file-based
  scenario runner") as a named-scenario SCR: runs a firm-supplied scenario
  set through `stresses.run_stress` (the SS8/18 five-step logic) and takes
  the worst own-funds loss as SCR, not a percentile of a simulated
  distribution.
- **`alm/reporting/`**: consolidates already-computed MA, hypothecation,
  matching-test, stress, RM and SCR results into one structured
  `ReportingPack` (deliverable: "MA pack, matching-test pack"), a markdown
  narrative, and a timestamped JSON export. **`malir.py`**: the narrower
  annual MA attestation data pack the brief names explicitly ("FS
  additions, HP cash-flow cap, matching evidence") -- those three
  components front and centre, not the full `ReportingPack`. Both are
  composed from results the caller already ran with the
  portfolio/scenario appropriate to each, rather than re-deriving a fixed
  pipeline internally.
- **`alm/config/`**: `FirmConfig`, the single place a firm's valuation
  date, base/reporting currencies, matching-bucket-frequency assumption,
  SCR mode and hypothecation algorithm choice, and reconciliation
  materiality tolerances live -- loadable/saveable as JSON (same pattern as
  `stresses.scenario_loader`). Doesn't force every function to take a
  config object (most of this engine's functions already take these values
  explicitly, a deliberately testable design this module doesn't change);
  instead exposes `reconciliation_kwargs()` so a firm edits one file rather
  than hunting through call sites. `material_tolerance`/`watch_tolerance`
  default to `validation.reconciliation`'s own constants, not a second,
  possibly-diverging copy. `matching_bucket_frequency` is documented as
  informational only -- this engine's cash flow models are annual
  throughout; the field names the assumption rather than silently leaving
  it implicit, but changing it doesn't yet reproject anything.

## Things that looked like bugs and weren't (or were, and got fixed)

1. **Same-time cash flow dicts must accumulate, not overwrite.** Early
   hypothecation/Test 1 code built `{cf.time: cf.amount for cf in flows}`,
   which silently *drops* earlier entries when two flows share a time (e.g. two
   Prophet model points both paying at t=5). Fixed everywhere this pattern
   occurred; `test_prophet_adapter.py::test_aggregation_sums_across_model_points_at_the_same_time`
   is the regression test for it. Audit any new code that builds a
   time-keyed dict from a `CashFlowVector` for the same mistake.
2. **A pure liability-cash-flow-scaling stress must NOT re-derive the MA
   rate from scratch against a fixed market value.** `two_aer`'s `r1` is
   defined as "the flat rate that reproduces *this* target PV for
   *whatever* cash flow shape it's given": it has no notion of adequacy.
   Scale the liability cash flows up 20% and re-solve `r1` against the same
   fixed MV, and `r1` inflates almost exactly enough to cancel the BEL
   increase, making a longevity shock look like a near-zero or even
   negative SCR. `scr/standard_formula.py::compute_longevity_scr` avoids
   this by holding the *base case's* MA rate fixed and only re-discounting
   the shocked liability cash flows at that fixed rate: the standard
   actuarial convention (life risk changes reserves via cash flows, not by
   retroactively re-pricing the asset side's credit spread). `stresses.run_stress`
   (used for market/credit/ORSA-style scenarios, where re-deriving the MA
   rate from a re-hypothecated portfolio *is* correct) intentionally does
   **not** use this shortcut: the two mechanisms are for different classes
   of stress and are not interchangeable. See both docstrings before adding
   a new stress type.
3. **An eligible-element product code (MA 2.3/2.5) was silently exempted
   from the future-premium check.** The original rule read "future premiums
   are disqualifying unless this is a recognised eligible element", which
   let `future_premium_flag=True` slide through for `WP_GUARANTEED_ELEMENT`
   / `IP_INPAY` / `GROUP_DIS_DEPENDANT`. That exemption is wrong: eligible
   elements are specifically *defined* as not depending on future premiums,
   so the flag being set on one is a data inconsistency, not a valid
   carve-out. Found by generating `ELIGIBILITY_MATRIX.md` and reading the
   row, not by a targeted test written in advance: fixed to fail closed
   unconditionally on `future_premium_flag`, regardless of product code.
   `alm/tests/test_eligibility_matrix.py::test_future_premium_flag_is_disqualifying_even_on_eligible_element_products`
   is the regression test.
4. **A markdown table helper had its Result and Threshold columns swapped.**
   `reporting/report.py`'s `_test_row` was defined as
   `(name, threshold_desc, result_desc, passed)` but called everywhere as
   `(name, result_desc, threshold_desc, passed)`, so every row in the
   rendered "PRA Matching Tests" table showed the threshold under "Result"
   and the actual result under "Threshold" (e.g. Test 1 showed "<= 3%" in
   the Result column and "68.41%" in the Threshold column). Caught by
   actually reading the rendered markdown output before writing the test,
   not by the test itself; fixed by reordering the function's parameters
   to match every call site.
   `alm/tests/test_reporting_pack.py::test_markdown_result_and_threshold_columns_are_not_swapped`
   is the regression test.
5. **Negative asset cash flows were silently dropped, not treated as an
   extra liability draw.** `hypothecation.py`'s Component A loop had
   `if cf.amount <= 0: continue`, discarding any negative cash flow
   entirely -- fine when every instrument's cash flows were non-negative
   (true of every instrument before `InterestRateSwap`), but understating
   what Component A/Test 1 actually needed to cover once a derivative's
   net-negative period existed: that outflow should INCREASE remaining
   liability at that bucket, not vanish. Fixed, and derivatives are now
   also excluded from Component A's PV-fraction assignment on separate
   grounds (a mixed-sign cash flow stream can make `assigned_pv/total_pv`
   exceed 1, which isn't a meaningful fraction).
6. **Component B's fraction guard checked the wrong sign.** The line
   `fraction_b[p.id] = take_mv / mv_p if mv_p > tolerance else 0.0` meant
   a genuinely negative `mv_p` (an out-of-the-money derivative) fell
   through to `0.0` even though `covered_mv` a line below was still
   correctly adjusted by the same `take_mv` -- so the position's entire
   value silently reappeared via Component C's `fraction_c = max(0, 1 -
   fa - fb)` fallback, double-counting it. The guard needed to test
   `abs(mv_p) > tolerance` (a negligible divisor), not `mv_p > tolerance`
   (a positive one). Caught by asserting the invariant
   `component_ab_market_value + component_c_market_value == total
   portfolio market value` on a portfolio actually containing a
   negative-MV position, not by eyeballing the numbers.
   `alm/tests/test_hypothecation_with_derivatives.py` covers both 5 and 6,
   plus a regression check that every existing bond-only portfolio's
   figures are byte-for-byte unchanged.

## Design decisions baked into the contracts (read before extending)

- **Sign convention**: `CashFlowVector.direction` ("liability_outgo" /
  "asset_income") carries sign meaning, not the numeric sign of `amount`
  (always a positive magnitude). `net_by_time` applies the actual netting
  (e.g. reinsurance recoveries subtract from outgo).
- **Curve interpolation**: linear-on-zero-rate between PRA term points,
  flat-extrapolated beyond the ends: swap in `Curve.zero_rate` if the
  firm's validated R code uses log-linear-on-discount-factor instead.
- **MA formula**: `MA = r1 - r2 - FS_rate`, cash-flow-level AERs (not a
  WAL/single-spread shortcut). `FS_rate` is a PV-weighted average of
  per-cash-flow FS lookups collapsed to one rate: see `ma/fs_rate.py` for
  where this simplifies the full per-flow-haircut method.
- **Gilts**: FS = 0 (`Bond.is_government=True`), per PRA convention, not a
  rating/sector lookup.
- **Component A/B/C**: PV-fraction based (not a single "units held" scalar
  per position): a scalar bounded by the worst cash-flow bucket would zero
  out an entire position's assignment because of one oversized/oversubscribed
  bucket elsewhere. See `ma/hypothecation.py` docstring.

## Not yet built (documented gaps, not silently skipped)

- Actual XBRL-style QRT structured filing output. `alm/reporting/`
  produces a structured pydantic/JSON object and markdown narratives (a
  general `ReportingPack` and the narrower MALIR-specific pack), which
  cover the deliverable's "QRT-like" and "MALIR hooks" language, but are
  not a real regulator-submittable filing format.
- `alm/market_data/` now has real RFR/FS loaders proven against both this
  project's own documented v1 long-format schema AND a real published Bank
  of England workbook (`load_rfr_curve_from_pra_workbook` /
  `load_fs_table_from_pra_workbook`, see `alm/market_data/pra_reference/`).
  The real-workbook adapters locate columns/headers by text search rather
  than a hardcoded index, but were only checked against the single 31 Aug
  2026 release -- treat that as reducing, not eliminating, the risk that a
  future release reshapes the file in a way this loader doesn't expect.
- The counterparty default SCR sub-module still uses an illustrative flat
  charge by counterparty rating, not the real Article 199 Type 1/Type 2
  loss-given-default/variance formula -- a deliberate scope decision (see
  `alm/scr/standard_formula.py` module docstring), not an oversight.
- `matching_bucket_frequency` in `alm/config/` is informational only: this
  engine's cash flow models are annual throughout, and changing the field
  doesn't reproject anything at a different frequency yet.

## Open inputs needed from the firm (defaults in place, isolated in config)

1. **Prophet extract schema**: no sample extract supplied yet; the v1
   default is documented in `prophet_io/extract_schema.py`. When a real
   extract is available, only that file (plus a thin column-rename
   mapping) needs to change.
2. **SCR mode**: confirmed: Standard Formula first, then the SS8/18
   internal-model interface. Set via `alm/config/`'s `FirmConfig.scr_mode`.
3. **Hypothecation algorithm**: confirmed default: greedy nearest-maturity
   per-time-bucket waterfall (`ma/hypothecation.py`), swappable. Set via
   `FirmConfig.hypothecation_algorithm`.
4. **PRA Test 2 shock calibration**: the interest-rate and FX legs now use
   the real PRA Rulebook Standard Formula calibration (see
   `alm/pra_calibration.py`); the inflation leg (`var_test.ShockSpec.inflation_shock`)
   remains an illustrative placeholder -- no published PRA/EIOPA inflation
   shock table was found. Every SCR sub-module except counterparty default
   (see "Not yet built" above) now uses real PRA Rulebook/Annex IV
   calibration, including both correlation matrices used in aggregation.
5. **Reconciliation materiality tolerances**: `FirmConfig.material_tolerance`
   / `watch_tolerance`, defaulting to `validation.reconciliation`'s existing
   2%/0.5% constants -- override per firm via a `FirmConfig` JSON file.
