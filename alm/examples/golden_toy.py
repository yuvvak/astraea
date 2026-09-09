"""Two hand-checkable golden scenarios, per repo README "implementation order":

Scenario A (gilt only): a 10y level annuity backed by a gilt priced exactly
off the same flat RFR curve. Because the asset is government (FS=0) and its
market value is set to exactly equal the basic-RFR BEL, both AERs collapse to
the flat RFR rate and MA must come out to 0.00bps -- this checks the AER
solver and the MA=r1-r2-FS wiring with no moving parts.

Scenario B (corporate bond): the same liability, backed by a smaller market
value of a single A2 non-financial corporate bond (i.e. the insurer has NOT
bought enough face value to cover the basic-RFR BEL -- only enough to cover
the smaller, MA-discounted reserve, which is the real-world funding
position). This produces a genuine positive MA, split into an asset-implied
spread net of FS.

Both scenarios use a flat RFR curve so r2 (the basic-RFR AER) is provably
exactly equal to the flat rate -- see alm/tests/test_golden_ma.py.
"""

from __future__ import annotations

from datetime import date

from alm.contracts.assets import AssetPosition, Bond, Cash
from alm.contracts.curves import Curve
from alm.contracts.fs import AssetSector, FSEntry, FSTable, RatingNotch
from alm.contracts.liabilities import LevelAnnuityCohort
from alm.ma.hp_instrument import HPBond

VALUATION_DATE = date(2026, 9, 8)
CURRENCY = "GBP"
RFR_FLAT_RATE = 0.04
LIABILITY_ANNUAL_PAYMENT = 100_000.0
LIABILITY_TERM_YEARS = 10.0


def build_liability() -> LevelAnnuityCohort:
    return LevelAnnuityCohort(
        id="toy_level_annuity_10y",
        currency=CURRENCY,
        annual_payment=LIABILITY_ANNUAL_PAYMENT,
        payment_frequency=1,
        term_years=LIABILITY_TERM_YEARS,
    )


def build_rfr_curve() -> Curve:
    return Curve.flat(RFR_FLAT_RATE, currency=CURRENCY, valuation_date=VALUATION_DATE, name="RFR_basic_flat_4pct")


def build_gilt_position(bel: float) -> AssetPosition:
    """Gilt priced at exactly `bel`: coupon set equal to the RFR (4%) so the
    bond prices at par, then notional is chosen equal to `bel` so MV == BEL
    to the penny -- makes Scenario A's MA == 0 an exact identity, not an
    approximation."""
    gilt = Bond(
        id="UKT_4pct_10y",
        currency=CURRENCY,
        notional=bel,
        coupon_rate=RFR_FLAT_RATE,
        coupon_frequency=1,
        maturity_years=LIABILITY_TERM_YEARS,
        rating=RatingNotch.AAA,
        sector=AssetSector.GOVERNMENT,
        is_government=True,
    )
    return AssetPosition(id="pos_gilt", instrument=gilt, units=1.0, market_value=None)


def build_corporate_bond_position(market_value: float) -> AssetPosition:
    """A2 non-financial 10y bond. `market_value` is supplied directly (as if
    quoted by the custodian/market) rather than derived from the coupon, to
    keep the golden MV a clean, hand-checkable round number."""
    bond = Bond(
        id="CORP_A2_4_75pct_10y",
        currency=CURRENCY,
        notional=780_000.0,
        coupon_rate=0.0475,
        coupon_frequency=1,
        maturity_years=LIABILITY_TERM_YEARS,
        rating=RatingNotch.A2,
        sector=AssetSector.NON_FINANCIAL,
        is_government=False,
    )
    return AssetPosition(id="pos_corp", instrument=bond, units=1.0, market_value=market_value)


def build_gilt5y_position(notional: float) -> AssetPosition:
    """A shorter (5y) gilt for the hypothecation/Test1/Test3 portfolio
    scenario -- priced at par (coupon = RFR = 4%) so MV == notional exactly,
    same trick as `build_gilt_position` but a different maturity so the
    nearest-maturity-first waterfall has something to order."""
    gilt = Bond(
        id="UKT_4pct_5y",
        currency=CURRENCY,
        notional=notional,
        coupon_rate=RFR_FLAT_RATE,
        coupon_frequency=1,
        maturity_years=5.0,
        rating=RatingNotch.AAA,
        sector=AssetSector.GOVERNMENT,
        is_government=True,
    )
    return AssetPosition(id="pos_gilt5y", instrument=gilt, units=1.0, market_value=None)


def build_hp_bond(notional: float = 500_000.0) -> HPBond:
    """A social-housing-style HP loan: expected bullet repayment at 10y,
    permitted to repay as early as 8y (Test 4) or as late as 13y with a
    step-up coupon (Test 5), rated A2 non-financial like the vanilla
    corporate bond so the same FS entry applies."""
    return HPBond(
        id="HP_A2_10y",
        currency=CURRENCY,
        notional=notional,
        coupon_rate=0.05,
        coupon_frequency=1,
        maturity_years=10.0,
        earliest_repayment_years=8.0,
        latest_repayment_years=13.0,
        step_up_rate=0.06,
        prudent_reinvestment_rate=0.03,  # spread-limited: below coupon_rate (5%)
        rating=RatingNotch.A2,
        sector=AssetSector.NON_FINANCIAL,
        is_government=False,
    )


def build_il_gilt_position(notional: float, assumed_inflation_rate: float = 0.025) -> AssetPosition:
    """A 10y index-linked gilt: 1.25% real coupon, cash flows uplifted by an
    illustrative flat 2.5% p.a. inflation assumption (documented placeholder,
    see Bond docstring), priced off the nominal RFR curve for simplicity."""
    il_gilt = Bond(
        id="UKTI_1_25pct_10y",
        currency=CURRENCY,
        notional=notional,
        coupon_rate=0.0125,
        coupon_frequency=1,
        maturity_years=LIABILITY_TERM_YEARS,
        rating=RatingNotch.AAA,
        sector=AssetSector.GOVERNMENT,
        is_government=True,
        inflation_linked=True,
        assumed_inflation_rate=assumed_inflation_rate,
    )
    return AssetPosition(id="pos_il_gilt", instrument=il_gilt, units=1.0, market_value=None)


def build_cash_position(notional: float) -> AssetPosition:
    cash = Cash(id="CASH_GBP", currency=CURRENCY, notional=notional)
    return AssetPosition(id="pos_cash", instrument=cash, units=1.0, market_value=None)


def build_usd_bond_position(market_value: float) -> AssetPosition:
    """A small USD-denominated corporate bond, purely to give PRA Test 2's
    currency VaR leg and the SF currency SCR sub-module a genuine non-zero
    exposure to exercise (both were always exactly 0 before, correctly, but
    untested against a real non-base-currency position)."""
    bond = Bond(
        id="CORP_USD_A3_5y",
        currency="USD",
        notional=market_value,
        coupon_rate=0.045,
        coupon_frequency=1,
        maturity_years=5.0,
        rating=RatingNotch.A3,
        sector=AssetSector.NON_FINANCIAL,
        is_government=False,
    )
    return AssetPosition(id="pos_usd_corp", instrument=bond, units=1.0, market_value=market_value)


def build_fs_table() -> FSTable:
    return FSTable(
        source="synthetic/golden-example",
        entries=(
            FSEntry(
                currency=CURRENCY, rating=RatingNotch.A2, sector=AssetSector.NON_FINANCIAL,
                term_years=50.0, fs_pd_bps=18.0, fs_cod_bps=7.0, ltas_floor_bps=0.0,
            ),
            FSEntry(
                currency="USD", rating=RatingNotch.A3, sector=AssetSector.NON_FINANCIAL,
                term_years=50.0, fs_pd_bps=20.0, fs_cod_bps=8.0, ltas_floor_bps=0.0,
            ),
            FSEntry(
                currency=CURRENCY, rating=RatingNotch.A2, sector=AssetSector.FINANCIAL,
                term_years=50.0, fs_pd_bps=22.0, fs_cod_bps=9.0, ltas_floor_bps=0.0,
            ),
        ),
    )
