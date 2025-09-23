from __future__ import annotations
import json
from pathlib import Path
from typing import Optional, Dict, Any
import typer
import pandas as pd
import os, sys, glob
import pulp

from ..io_config import read_yaml, load_timeseries_from_config, baseline_from_profiles
from ..model_lp import build_and_solve_lp
from ..economics import assemble_cashflows_year1_constant
from ..reporting.html_report import generate_html_report_lp


def _peaks_monthly(net_kw: pd.Series) -> Dict[str, float]:
    idx = net_kw.index
    if isinstance(idx, pd.DatetimeIndex):
        # Zeitzone entfernen, falls vorhanden
        if idx.tz is not None:
            idx = idx.tz_convert(None)
        months = idx.to_period("M")
        df = pd.DataFrame({"v": net_kw.values, "m": months})
        by_m = df.groupby("m")["v"].max()
        return {str(k): float(v) for k, v in by_m.items()}

    # Kein DatetimeIndex: nur Jahrespeak zurückgeben
    vmax = float(pd.Series(net_kw).max())
    return {"year": vmax}

def _find_cbc_path() -> str | None:
    """Suche die mit PuLP gebundelte cbc(.exe)."""
    try:
        root = os.path.dirname(pulp.__file__)
        patterns = ["**/cbc.exe", "**/cbc"] if os.name == "nt" else ["**/cbc"]
        for pat in patterns:
            cands = glob.glob(os.path.join(root, pat), recursive=True)
            if cands:
                return cands[0]
    except Exception:
        pass
    return None

def _solve_with_cbc(prob, *, msg: bool = True, time_limit: int | None = None, threads: int | None = None):
    """Erzwinge CBC – kein HiGHS/GLPK Fallback."""
    cbc_path = _find_cbc_path()
    if msg:
        print(f"[battopt_lp] Using CBC at: {cbc_path or 'PATH'}", file=sys.stderr)
    solver = pulp.PULP_CBC_CMD(
        msg=1 if msg else 0,
        timeLimit=time_limit,
        threads=threads,
        path=cbc_path,   # darf None sein; dann nimmt PuLP den PATH
    )
    status = prob.solve(solver)
    return status

app = typer.Typer(add_completion=False, help="Option 4 – Jahres-LP Optimierer (EV + Peak Shaving).")

@app.command()
def main(
    config: str = typer.Option(..., help="Pfad zur YAML (Timeseries + Preise + Ökonomie)"),
    report_html: Optional[str] = typer.Option(None, help="HTML-Report (optional)"),
    series_csv: Optional[str] = typer.Option(None, help="Timeseries-CSV ausgeben"),
    solver: str = typer.Option("CBC", help="CBC | GLPK | HiGHS  (CBC empfohlen)")
):
    cfg = read_yaml(config)
    cons, pv, step_hours, tz = load_timeseries_from_config(cfg)
    base = baseline_from_profiles(cons, pv)

    # Params
    st = cfg.get("storage", {}).get("simulate", {})
    params = {
        "capacity_kwh": float(st.get("capacity_kwh", 0.0)),
        "p_charge_kw": float(st.get("p_charge_kw", 0.0)),
        "p_discharge_kw": float(st.get("p_discharge_kw", 0.0)),
        "roundtrip_eff": float(st.get("roundtrip_eff", 0.92)),
        "soc_min": float(st.get("soc_min", 0.05)),
        "soc_max": float(st.get("soc_max", 0.95)),
        "soc0": float(st.get("soc0", 0.5)),
    }
    prices_raw = cfg.get("energy_prices", {})
    prices = {
        "import_chf_per_kWh": float(prices_raw.get("import_chf_per_kWh", prices_raw.get("import_price_chf_per_kWh", 0.0))),
        "grid_chf_per_kWh": float(prices_raw.get("grid_chf_per_kWh", prices_raw.get("grid_price_chf_per_kWh", 0.0))),
        "feed_in_chf_per_kWh": float(prices_raw.get("feed_in_chf_per_kWh", prices_raw.get("feed_in_price_chf_per_kWh", 0.0))),
    }
    demand_cfg = cfg.get("demand_tariff", {})
    cap_kW = (cfg.get("remuneration", {}) or {}).get("paid_feed_in_cap_kW", None)
    cap_kWh = (float(cap_kW) * step_hours) if (cap_kW is not None) else None

    # Solve
    res = build_and_solve_lp(
        index=cons.index,
        step_hours=step_hours,
        load_kWh=cons,
        pv_kWh=pv,
        prices=prices,
        params=params,
        demand_cfg=demand_cfg,
        remuneration_cap_kWh=cap_kWh,
        cyclic=True,
        solver=solver,  # <- kommt jetzt aus der CLI, Default "CBC"
    )

    # KPIs (year-1 energy & demand economics)
    # Baseline
    import0_kWh = float(((cons - pv).clip(lower=0)).sum())
    feed0_paid_kWh = float((pv - cons).clip(lower=0).clip(upper=cap_kWh if cap_kWh is not None else 1e18).sum())

    # With storage
    imp1 = res["import_series_kWh"]
    exp1 = res["pv_export_kWh"]
    paid1 = res["pv_export_paid_kWh"]

    import1_kWh = float(imp1.sum())
    feed1_paid_kWh = float(paid1.sum())

    SC1 = float(cons.sum() - import1_kWh)

    import_savings = (import0_kWh - import1_kWh) * prices["import_chf_per_kWh"]
    lost_feed_rev  = (feed0_paid_kWh - feed1_paid_kWh) * prices["feed_in_chf_per_kWh"]

        # Demand baseline/with (monthly or annual)
    basis_cfg = (demand_cfg.get("basis", "monthly") or "monthly").lower()
    charge = float(demand_cfg.get("charge_chf_per_kW", 0.0))
    h = step_hours

    # Wenn kein DatetimeIndex vorhanden ist, auf "annual" umschalten
    index_is_dt = isinstance(cons.index, pd.DatetimeIndex)
    basis = basis_cfg if index_is_dt else "annual"

    if basis == "annual":
        net0_kw = ((cons - pv).clip(lower=0) / h)
        net1_kw = (imp1 / h)
        peak0 = float(net0_kw.max())
        peak1 = float(net1_kw.max())
        cost0 = charge * peak0
        cost1 = charge * peak1
        monthly_before = {}
        monthly_after = {}
    else:
        net0_kw = ((cons - pv).clip(lower=0) / h)
        net1_kw = (imp1 / h)
        monthly_before = _peaks_monthly(net0_kw)
        monthly_after  = _peaks_monthly(net1_kw)
        cost0 = sum(monthly_before.values()) * charge
        cost1 = sum(monthly_after.values()) * charge

    demand_savings = float(cost0 - cost1)


    grid_charge_energy = float(res.get("grid_charge_kWh", pd.Series(0, index=cons.index)).sum())
    grid_charge_cost   = float(grid_charge_energy * prices["grid_chf_per_kWh"])

    gross_benefit_y1 = float(import_savings - lost_feed_rev + demand_savings - grid_charge_cost)
    econ_raw = cfg.get("economics", {}) or cfg.get("econ", {}) or {}
    capex_bat = float(econ_raw.get("capex_battery_chf", econ_raw.get("battery_capex_chf", 0.0)))
    capex_inst= float(econ_raw.get("capex_installation_chf", econ_raw.get("installation_capex_chf", 0.0)))
    opex_year = float(econ_raw.get("opex_annual_chf", econ_raw.get("opex_chf_per_year", 0.0)))
    lifetime  = int(econ_raw.get("lifetime_years", 15))
    dr_pct    = float(econ_raw.get("discount_rate_pct", 4.0))
    subsidy   = float(econ_raw.get("subsidy_upfront_chf", 0.0))

    annual_net_benefit_y1 = gross_benefit_y1 - opex_year
    capex_total = capex_bat + capex_inst - subsidy

    fin = assemble_cashflows_year1_constant(
        benefit_year1=annual_net_benefit_y1,
        years=lifetime,
        capex_total=capex_total,
        discount_rate_pct=dr_pct,
    )

    out = {
        "status": res["status"],
        "objective_value": res["objective"],
        "SC1_kWh": SC1,
        "delta_import_kWh": float(import0_kWh - import1_kWh),
        "import_savings_chf_year1": float(import_savings),
        "lost_feed_in_revenue_chf_year1": float(lost_feed_rev),
        "gross_benefit_chf_year1": float(gross_benefit_y1),
        "annual_net_benefit_chf_year1": float(annual_net_benefit_y1),
        "capex_total_chf": float(capex_bat + capex_inst),
        "subsidy_upfront_chf_applied": float(subsidy),
        "capex_net_chf": float(capex_total),
        "npv_chf": fin["npv_chf"],
        "irr": fin["irr"],
        "discounted_payback_years": fin["discounted_payback_years"],
        "cashflows": fin["cashflows"],
        "cashflows_disc": fin["cashflows_disc"],
        "cashflows_undisc": fin["cashflows_undisc"],
        "demand_charge_cost_baseline_chf_year1": float(cost0),
        "demand_charge_cost_with_storage_chf_year1": float(cost1),
        "demand_charge_savings_chf_year1": float(demand_savings),
        "grid_charge_energy_kWh_year1": float(grid_charge_energy),
        "grid_charge_cost_chf_year1": float(grid_charge_cost),
        "timeseries_baseline": base,
        "demand": {
            "enabled": bool(demand_cfg.get("enabled", False)),
            "basis": basis,
            "charge_chf_per_kW": float(demand_cfg.get("charge_chf_per_kW", 0.0)),
            "monthly_peak_before_kW": monthly_before,
            "monthly_peak_after_kW": monthly_after,
        },
    }

    # Write CSV if requested
    if series_csv:
        Path(series_csv).parent.mkdir(parents=True, exist_ok=True)
            # Build series DataFrame (always in-memory)
    df = pd.DataFrame({
        "consumption_kWh": cons,
        "pv_generation_kWh": pv,
        "import_with_storage_kWh": res["import_series_kWh"],
        "pv_export_kWh": res["pv_export_kWh"],
        "pv_export_paid_kWh": res["pv_export_paid_kWh"],
        "pv2load_kWh": res["pv2load_kWh"],
        "pv2batt_kWh": res["pv2batt_kWh"],
        "grid2load_kWh": res["grid2load_kWh"],
        "battery_charge_kWh": res["battery_charge_kWh"],
        "battery_discharge_kWh": res["battery_discharge_kWh"],
        "battery_soc_kWh": res["battery_soc_kWh"],
    })
    if "grid_charge_kWh" in res:
        df["grid_charge_kWh"] = res["grid_charge_kWh"]
    df.index.name = "step"  # robust for non-datetime indices

    # Write CSV if requested
    if series_csv:
        Path(series_csv).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(series_csv, float_format="%.10g")
        print(f"Wrote timeseries CSV -> {series_csv}")

    # Pretty HTML report
    if report_html:
        Path(report_html).parent.mkdir(parents=True, exist_ok=True)

        df_for_report = df.copy()  # <— copy, um Seiteneffekte zu vermeiden

        if "step" not in df_for_report.columns:
            if isinstance(df_for_report.index, pd.DatetimeIndex):
                idx_name = df_for_report.index.name or "index"
                df_for_report = df_for_report.reset_index().rename(columns={idx_name: "step"})
            else:
                # zusätzliche Aliase abdecken
                for alias in ("datetime", "timestamp", "time", "ts"):
                    if alias in df_for_report.columns:
                        df_for_report = df_for_report.rename(columns={alias: "step"})
                        break
                # wenn gar nichts passt, lässt generate_html_report_lp KeyError werfen

        generate_html_report_lp(out, df_for_report, step_hours, report_html, cfg)
        out["report_html_path"] = report_html

    print(json.dumps(out, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    app()
