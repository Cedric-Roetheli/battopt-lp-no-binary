from __future__ import annotations
from typing import Dict, Any
import pandas as pd
import pulp
import os, glob

# --------- CBC Finder & Solver ---------

def _find_cbc_path() -> str | None:
    try:
        root = os.path.dirname(pulp.__file__)
        pats = ["**/cbc.exe", "**/cbc"] if os.name == "nt" else ["**/cbc"]
        for pat in pats:
            cands = glob.glob(os.path.join(root, pat), recursive=True)
            if cands:
                return cands[0]
    except Exception:
        pass
    return None

def _cbc_solver(msg: bool = False):
    path = _find_cbc_path()
    if path:
        return pulp.COIN_CMD(path=path, msg=1 if msg else 0)
    return pulp.PULP_CBC_CMD(msg=1 if msg else 0)

# --------- LP Builder ---------

def build_and_solve_lp(
    index: pd.Index,
    step_hours: float,
    load_kWh: pd.Series,
    pv_kWh: pd.Series,
    prices: Dict[str, float],
    params: Dict[str, float],
    demand_cfg: Dict[str, Any],
    remuneration_cap_kWh: float | None,
    cyclic: bool = True,
    solver: str = "CBC",
) -> Dict[str, Any]:

    # unpack params
    C = float(params.get("capacity_kwh", 0.0))
    Pch = float(params.get("p_charge_kw", 0.0))
    Pdis = float(params.get("p_discharge_kw", 0.0))
    eta_rt = float(params.get("roundtrip_eff", 0.92))
    eta_c = eta_rt ** 0.5
    eta_d = eta_rt ** 0.5
    soc_min = float(params.get("soc_min", 0.05)) * C
    soc_max = float(params.get("soc_max", 0.95)) * C
    soc0    = float(params.get("soc0", 0.5)) * C

    imp_p  = float(prices.get("import_chf_per_kWh", 0.0))
    feed_p = float(prices.get("feed_in_chf_per_kWh", 0.0))
    grid_p = float(prices.get("grid_chf_per_kWh", 0.0))

    allow_grid_ch   = bool(demand_cfg.get("allow_grid_charging", True))
    demand_enabled  = bool(demand_cfg.get("enabled", False))
    charge_per_kW   = float(demand_cfg.get("charge_chf_per_kW", 0.0))
    basis_requested = (demand_cfg.get("basis", "monthly") or "monthly").lower()

    h = float(step_hours)
    Pch_e = Pch * h
    Pdis_e = Pdis * h

    T = range(len(index))
    m = pulp.LpProblem("battopt_lp", pulp.LpMaximize)

    # Vars
    e   = pulp.LpVariable.dicts("e",   T, lowBound=soc_min, upBound=soc_max, cat="Continuous")
    ch  = pulp.LpVariable.dicts("ch",  T, lowBound=0, upBound=Pch_e,  cat="Continuous")  # AC charge
    dis = pulp.LpVariable.dicts("dis", T, lowBound=0, upBound=Pdis_e, cat="Continuous")  # AC discharge

    pv2load = pulp.LpVariable.dicts("pv2load", T, lowBound=0, cat="Continuous")
    pv2batt = pulp.LpVariable.dicts("pv2batt", T, lowBound=0, cat="Continuous")
    pv2exp  = pulp.LpVariable.dicts("pv2exp",  T, lowBound=0, cat="Continuous")

    grid2load   = pulp.LpVariable.dicts("grid2load", T, lowBound=0, cat="Continuous")
    grid_charge = pulp.LpVariable.dicts("grid_charge", T, lowBound=0, cat="Continuous") if allow_grid_ch else {t: 0 for t in T}
    imp         = pulp.LpVariable.dicts("imp", T, lowBound=0, cat="Continuous")
    paid_exp    = pulp.LpVariable.dicts("paid_exp", T, lowBound=0, cat="Continuous")

    # SoC dynamics
    for t in T:
        prev = (t - 1) % len(T)
        if t == 0 and not cyclic:
            m += e[t] == soc0 + eta_c * ch[t] - (1.0 / eta_d) * dis[t]
        else:
            m += e[t] == e[prev] + eta_c * ch[t] - (1.0 / eta_d) * dis[t]

    if cyclic:
        m += e[len(T) - 1] == e[0]

    # PV balance & charge split
    for t in T:
        G = float(pv_kWh.iloc[t])
        m += pv2load[t] + pv2batt[t] + pv2exp[t] == G
        if allow_grid_ch:
            m += ch[t] == pv2batt[t] + grid_charge[t]
        else:
            m += ch[t] == pv2batt[t]

    # Load balance
    for t in T:
        L = float(load_kWh.iloc[t])
        m += pv2load[t] + dis[t] + grid2load[t] == L

    # Import definition
    for t in T:
        if allow_grid_ch:
            m += imp[t] == grid2load[t] + grid_charge[t]
        else:
            m += imp[t] == grid2load[t]

    # Paid export cap
    if remuneration_cap_kWh is not None:
        for t in T:
            m += paid_exp[t] <= pv2exp[t]
            m += paid_exp[t] <= float(remuneration_cap_kWh)
    else:
        for t in T:
            m += paid_exp[t] == pv2exp[t]

    # Demand charges
    demand_cost = 0.0
    peak_vars: Dict[str, pulp.LpVariable] = {}

    is_dt = isinstance(index, pd.DatetimeIndex)
    use_annual = (basis_requested == "annual") or (not is_dt)

    if demand_enabled and charge_per_kW > 0:
        if use_annual:
            P = pulp.LpVariable("peak_year", lowBound=0, cat="Continuous")
            for t in T:
                m += (imp[t] / h) <= P
            demand_cost = charge_per_kW * P
            peak_vars["year"] = P
        else:
            months = index.tz_convert(None).to_period("M") if index.tz is not None else index.to_period("M")
            months = [str(p) for p in months]
            mnames = sorted(list(dict.fromkeys(months)))
            Pm = {mn: pulp.LpVariable(f"peak_{mn}", lowBound=0, cat="Continuous") for mn in mnames}
            for t in T:
                m += (imp[t] / h) <= Pm[months[t]]
            demand_cost = sum(charge_per_kW * Pm[mn] for mn in mnames)
            peak_vars.update(Pm)

    # Objective
    feed_rev = sum(paid_exp[t] * feed_p for t in T)
    imp_cost = sum(imp[t] * imp_p for t in T)
    grid_cost = sum((grid_charge[t] if allow_grid_ch else 0) * grid_p for t in T)
    m += feed_rev - imp_cost - grid_cost - demand_cost

    # Solve
    solver = (solver or "CBC").strip().lower()
    if solver == "glpk":
        s = pulp.GLPK_CMD(msg=False)
    elif solver == "highs":
        try:
            s = pulp.HiGHS_CMD(msg=False)
        except Exception:
            s = _cbc_solver(msg=False)
    else:
        s = _cbc_solver(msg=False)

    try:
        m.solve(s)
    except Exception:
        if solver == "highs":
            m.solve(_cbc_solver(msg=False))
        else:
            raise

    status = pulp.LpStatus[m.status]

    # Results
    def _ser(d):
    # Werte in Zeitreihen-Reihenfolge 0..T-1 einsammeln und dem DatetimeIndex zuordnen
        return pd.Series([float(d[t].value()) for t in T], index=index)


    res = {
        "status": status,
        "objective": float(pulp.value(m.objective)),
        "import_series_kWh": _ser(imp),
        "pv_export_kWh": _ser(pv2exp),
        "pv_export_paid_kWh": _ser(paid_exp),
        "pv2load_kWh": _ser(pv2load),
        "pv2batt_kWh": _ser(pv2batt),
        "grid2load_kWh": _ser(grid2load),
        "battery_charge_kWh": _ser(ch),
        "battery_discharge_kWh": _ser(dis),
        "battery_soc_kWh": _ser(e),
    }
    if allow_grid_ch:
        res["grid_charge_kWh"] = _ser(grid_charge)

    if peak_vars:
        if "year" in peak_vars:
            res["annual_peak_after_kW"] = float(peak_vars["year"].value())
        else:
            res["monthly_peak_after_kW"] = {
                k.replace("peak_", ""): float(v.value()) for k, v in peak_vars.items()
            }

    return res
