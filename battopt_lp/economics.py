from __future__ import annotations
from typing import Dict, List, Optional
import math

def npv(rate: float, cashflows: List[float]) -> float:
    return float(sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cashflows)))

def irr_bisect(cashflows: List[float], guess_low: float = -0.9, guess_high: float = 1.5, tol: float = 1e-7, max_iter: int = 200) -> Optional[float]:
    f_low = npv(guess_low, cashflows)
    f_high = npv(guess_high, cashflows)
    if f_low * f_high > 0:
        return None
    low, high = guess_low, guess_high
    for _ in range(max_iter):
        mid = (low + high) / 2.0
        f_mid = npv(mid, cashflows)
        if abs(f_mid) < tol:
            return mid
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return mid

def discounted_payback(cashflows: List[float], rate: float) -> Optional[float]:
    acc = 0.0
    for t, cf in enumerate(cashflows):
        acc += cf / ((1.0 + rate) ** t)
        if acc >= 0:
            prev_acc = acc - cf / ((1.0 + rate) ** t)
            if cf == 0:
                return float(t)
            frac = (0 - prev_acc) / (cf / ((1.0 + rate) ** t))
            return float(t - 1 + frac)
    return None

def assemble_cashflows_year1_constant(
    benefit_year1: float,
    years: int,
    capex_total: float,
    discount_rate_pct: float,
) -> Dict[str, object]:
    cash = [-float(capex_total)] + [float(benefit_year1)] * years
    dr = float(discount_rate_pct) / 100.0
    return {
        "cashflows": cash,
        "npv_chf": npv(dr, cash),
        "irr": irr_bisect(cash),
        "discounted_payback_years": discounted_payback(cash, dr),
        "cashflows_disc": [cf / ((1.0 + dr) ** t) for t, cf in enumerate(cash)],
        "cashflows_undisc": [cf / ((1.0 + dr) ** t) for t, cf in enumerate(cash)],  # compat
    }
