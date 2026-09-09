"""Single-annual-effective-rate (AER) solver.

Given a cash flow vector and a target present value, find the single flat
annual effective rate r such that PV(cash flows, r) = target_pv. This is the
mechanical core of the "two annual effective rates" MA definition in
SS7/18 4.3-4.17: one AER makes the liability cash flows equal to the assigned
asset market value, the other makes them equal to the basic-RFR BEL; MA is
(approximately) the difference between the two, net of FS.
"""

from __future__ import annotations

from alm.contracts.cashflows import CashFlowVector

from scipy.optimize import brentq


class AERSolverError(RuntimeError):
    pass


def solve_aer(cfv: CashFlowVector, target_pv: float, lo: float = -0.5, hi: float = 2.0, xtol: float = 1e-12) -> float:
    """Solve for the flat annual effective rate r in (lo, hi) such that
    cfv.pv_flat(r) == target_pv. PV is strictly decreasing in r for any
    all-non-negative cash flow vector with at least one positive flow, so the
    root (if bracketed) is unique.
    """
    if not cfv.flows:
        raise AERSolverError(f"cannot solve AER for empty cash flow vector {cfv.id!r}")
    if target_pv <= 0:
        raise AERSolverError(f"target_pv must be positive, got {target_pv}")

    def f(r: float) -> float:
        return cfv.pv_flat(r) - target_pv

    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        raise AERSolverError(
            f"AER root not bracketed for {cfv.id!r}: f({lo})={f_lo:.6f}, f({hi})={f_hi:.6f}. "
            f"target_pv={target_pv}, total_undiscounted={cfv.total()}"
        )
    return float(brentq(f, lo, hi, xtol=xtol))
