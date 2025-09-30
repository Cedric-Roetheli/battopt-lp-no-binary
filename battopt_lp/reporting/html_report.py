
import io, base64, json
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def _b64(fig):
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")

def _ensure_step(df, tz="Europe/Zurich"):
    dfx = df.copy()
    if "step" not in dfx.columns:
        if isinstance(dfx.index, pd.DatetimeIndex):
            dfx = dfx.reset_index().rename(columns={dfx.index.name or "index": "step"})
        else:
            for alias in ("datetime","timestamp","time","ts"):
                if alias in dfx.columns:
                    dfx = dfx.rename(columns={alias:"step"})
                    break
    s = pd.to_datetime(dfx["step"], utc=True, errors="coerce").dt.tz_convert(tz)
    dfx["step"] = s
    return dfx

def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def _npv(rate, cashflows):
    return sum(cf/((1+rate)**i) for i, cf in enumerate(cashflows))

def _irr(cashflows, guess=0.1, tol=1e-7, it=100):
    x0, x1 = guess, guess+0.1
    f0 = _npv(x0, cashflows)
    f1 = _npv(x1, cashflows)
    for _ in range(it):
        if abs(f1-f0) < 1e-12:
            break
        x2 = x1 - f1*(x1-x0)/(f1-f0)
        f2 = _npv(x2, cashflows)
        if abs(f2) < tol:
            return x2
        x0, f0, x1, f1 = x1, f1, x2, f2
    return float("nan")

def generate_html_report_lp(out, df, step_hours, out_path, cfg=None):
    """
    Display-first Report: nutzt 'out' (aus economics/model) als Quelle, berechnet nur,
    wenn Werte fehlen. Visualisierungen bleiben leichtgewichtig.
    """
    cfg = cfg or {}
    tz = (cfg.get("timeseries") or {}).get("tz", "Europe/Zurich")
    step_seconds = int((cfg.get("timeseries") or {}).get("step_seconds", (step_hours or 0)*3600 or 900))
    if not step_hours or step_hours <= 0:
        step_hours = step_seconds/3600.0

    df = _ensure_step(df, tz).sort_values("step").reset_index(drop=True)

    prices = cfg.get("energy_prices", {})
    demand = cfg.get("demand_tariff", {})
    econ   = cfg.get("economics", {})
    storage= (cfg.get("storage") or {}).get("simulate", {})
    remuner= cfg.get("remuneration", {})

    import_rate = _safe_float(prices.get("import_chf_per_kWh", 0.19))
    feed_rate   = _safe_float(prices.get("feed_in_chf_per_kWh", 0.06))
    dc_rate     = _safe_float(demand.get("charge_chf_per_kW", 12.0))
    lifetime    = int(econ.get("lifetime_years", 15))
    dr          = _safe_float(econ.get("discount_rate_pct", 2.0))/100.0

    cons = df.get("consumption_kWh", pd.Series(0, index=df.index)).astype(float)
    pv   = df.get("pv_generation_kWh", pd.Series(0, index=df.index)).astype(float)

    load_total = _safe_float(out.get("load_total_kWh", (out.get("base") or {}).get("load_total_kWh", cons.sum())))
    pv_total   = _safe_float(out.get("pv_total_kWh", (out.get("base") or {}).get("pv_total_kWh", pv.sum())))

    import0 = out.get("import0_kWh", (out.get("base") or {}).get("import_no_storage_kWh", None))
    import1 = out.get("import1_kWh", None)
    if import0 is None:
        import0 = float((cons - pv).clip(lower=0).sum())
    if import1 is None:
        if "import_with_storage_kWh" in df.columns:
            import1 = float(df["import_with_storage_kWh"].astype(float).sum())
        else:
            import1 = float((df.get("grid2load_kWh", pd.Series(0, index=df.index)).astype(float) +
                             df.get("grid_charge_kWh", pd.Series(0, index=df.index)).astype(float)).sum())

    sc0 = out.get("SC0_kWh", (out.get("base") or {}).get("self_consumption_no_storage_kWh", None))
    sc1 = out.get("SC1_kWh", None)
    if sc0 is None:
        sc0 = float(np.minimum(cons, pv).sum())
    if sc1 is None:
        pv2load = df.get("pv2load_kWh", pd.Series(0, index=df.index)).astype(float).sum()
        eff = float(out.get("roundtrip_eff", storage.get("roundtrip_eff", 0.92)))
        pv2batt = df.get("pv2batt_kWh", pd.Series(0, index=df.index)).astype(float)
        batt_dis= df.get("battery_discharge_kWh", pd.Series(0, index=df.index)).astype(float)
        sc1 = float(pv2load + np.minimum(batt_dis, pv2batt*eff).sum())

    evq_before = (sc0 / (pv_total if pv_total>0 else 1.0))*100.0
    evq_after  = (sc1 / (pv_total if pv_total>0 else 1.0))*100.0
    autark_before = (1 - import0/(load_total if load_total>0 else 1.0))*100.0
    autark_after  = (1 - import1/(load_total if load_total>0 else 1.0))*100.0

    if "monthly_before" in out and "monthly_after" in out:
        mb = pd.Series(out["monthly_before"], dtype=float)
        ma = pd.Series(out["monthly_after"], dtype=float)
        mb.index = pd.PeriodIndex(mb.index, freq="M")
        ma.index = pd.PeriodIndex(ma.index, freq="M")
        m_before_kw = mb.sort_index()
        m_after_kw  = ma.sort_index().reindex(m_before_kw.index)
    else:
        kw_before = ((cons - pv).clip(lower=0)/step_hours)
        imp_after_series = (df["import_with_storage_kWh"].astype(float) if "import_with_storage_kWh" in df.columns
                            else (df.get("grid2load_kWh", pd.Series(0, index=df.index)).astype(float) +
                                  df.get("grid_charge_kWh", pd.Series(0, index=df.index)).astype(float)))
        kw_after = (imp_after_series.clip(lower=0)/step_hours)
        period_m = df["step"].dt.to_period("M")
        m_before_kw = kw_before.groupby(period_m).max()
        m_after_kw  = kw_after.groupby(period_m).max().reindex(m_before_kw.index)

    demand_savings_chf = _safe_float(out.get("demand_savings_chf_year1", out.get("demand_savings_chf", None)))
    if np.isnan(demand_savings_chf) or demand_savings_chf == 0.0:
        demand_savings_chf = float(((m_before_kw - m_after_kw).clip(lower=0) * dc_rate).sum())

    import_savings_chf = _safe_float(out.get("import_savings_chf_year1", out.get("import_savings_chf", None)))
    if np.isnan(import_savings_chf) or import_savings_chf == 0.0:
        import_savings_chf = float((import0 - import1) * import_rate)

    feed_delta_chf = _safe_float(out.get("lost_feed_in_revenue_chf_year1", None))
    if feed_delta_chf is None:
        paid_after = df.get("pv_export_paid_kWh", pd.Series(0, index=df.index)).astype(float).sum()
        paid_before = float((pv - np.minimum(cons, pv)).clip(lower=0).sum())
        feed_delta_chf = (paid_after - paid_before) * feed_rate

    gross_benefit_y1 = _safe_float(out.get("gross_benefit_chf_year1", None))
    if np.isnan(gross_benefit_y1) or gross_benefit_y1 == 0.0:
        gross_benefit_y1 = import_savings_chf + demand_savings_chf + feed_delta_chf

    capex_total = _safe_float(out.get("capex_total_chf", None))
    if capex_total == 0.0:
        capex_total = (_safe_float(econ.get("capex_battery_chf", 0)) +
                       _safe_float(econ.get("capex_installation_chf", 0)) -
                       _safe_float(econ.get("subsidy_upfront_chf", 0)))

    opex = _safe_float(econ.get("opex_annual_chf", 0.0))
    annual_net_benefit = _safe_float(out.get("annual_net_benefit_chf_year1", None))
    if np.isnan(annual_net_benefit) or annual_net_benefit == 0.0:
        annual_net_benefit = gross_benefit_y1 - opex

    npv_chf = out.get("npv_chf", None)
    irr_val = out.get("irr", None)
    dpb     = out.get("discounted_payback_years", None)
    if npv_chf is None or irr_val is None or dpb is None:
        cfs = [-capex_total] + [annual_net_benefit for _ in range(lifetime)]
        npv_chf = _npv(dr, cfs)
        try:
            irr_val = _irr(cfs)
        except Exception:
            irr_val = float("nan")
        cum_disc = 0.0
        dpb = None
        for i, cf in enumerate(cfs):
            cum_disc += cf/((1+dr)**i)
            if cum_disc >= 0 and dpb is None:
                dpb = i

    kpi = {
        "Zeitraum": f'{df["step"].min().date()} → {df["step"].max().date()}',
        "Zeitschritt": f"{step_seconds/3600:.2f} h",
        "Verbrauch gesamt": f"{load_total:,.0f} kWh",
        "PV-Erzeugung gesamt": f"{pv_total:,.0f} kWh",
        "Import vorher/nachher": f"{import0:,.0f} / {import1:,.0f} kWh",
        "Δ Import": f"{(import0-import1):,.0f} kWh",
        "Monats-Peak max Vor/Nach": f"{m_before_kw.max():.1f} / {m_after_kw.max():.1f} kW",
        "EVQ Vor/Nach": f"{evq_before:.1f}% / {evq_after:.1f}%",
        "Autarkie Vor/Nach": f"{autark_before:.1f}% / {autark_after:.1f}%",
        "Demand-Ersparnis Y1": f"{demand_savings_chf:,.0f} CHF",
        "Import-Ersparnis Y1": f"{import_savings_chf:,.0f} CHF",
        "Δ Einspeisevergütung Y1": f"{feed_delta_chf:,.0f} CHF",
        "Nettonutzen Y1": f"{annual_net_benefit:,.0f} CHF",
        "Capex (netto)": f"{capex_total:,.0f} CHF",
        "NPV": f"{npv_chf:,.0f} CHF",
        "IRR": f"{(irr_val*100 if irr_val==irr_val else float('nan')):.1f}%",
        "Discounted Payback": f"{dpb} Jahre" if dpb is not None else "n/a",
    }

    images = {}

    # EVQ
    fig, ax = plt.subplots(figsize=(5.4,3.2))
    ax.bar([0,1],[evq_before, evq_after])
    ax.set_xticks([0,1], ["ohne Batterie", "mit Batterie"])
    ax.set_ylabel("Eigenverbrauchsquote [%]")
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    images["evq"] = _b64(fig)

    # Autarkie
    fig, ax = plt.subplots(figsize=(5.4,3.2))
    ax.bar([0,1],[autark_before, autark_after])
    ax.set_xticks([0,1], ["ohne Batterie", "mit Batterie"])
    ax.set_ylabel("Autarkie [%]")
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    images["autarkie"] = _b64(fig)

    # Peaks monthly
    fig, ax = plt.subplots(figsize=(5.4,3.2))
    x = np.arange(len(m_before_kw)); width = 0.38
    ax.bar(x-width/2, m_before_kw.values, width, label="ohne Batterie")
    ax.bar(x+width/2, m_after_kw.values, width, label="mit Batterie")
    ax.set_xticks(x, [str(p) for p in m_before_kw.index], rotation=45, ha="right")
    ax.set_ylabel("Monats-Peak [kW]")
    ax.legend()
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    images["peaks_monthly"] = _b64(fig)

    # Duration curve
    kw_before_series = ((cons - pv).clip(lower=0)/step_hours)
    imp_after_series = (df["import_with_storage_kWh"].astype(float) if "import_with_storage_kWh" in df.columns
                        else (df.get("grid2load_kWh", pd.Series(0, index=df.index)).astype(float) +
                              df.get("grid_charge_kWh", pd.Series(0, index=df.index)).astype(float)))
    kw_after_series  = (imp_after_series.clip(lower=0)/step_hours)
    a = np.sort(kw_before_series.values); b = np.sort(kw_after_series.values)
    fig, ax = plt.subplots(figsize=(5.4,3.2))
    ax.plot(np.linspace(0,100,len(a)), a, label="ohne Batterie")
    ax.plot(np.linspace(0,100,len(b)), b, label="mit Batterie")
    ax.set_xlabel("Prozent der Zeit [%]")
    ax.set_ylabel("Netto-Last [kW]")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()
    images["duration_curve"] = _b64(fig)

    # Energy split monthly (after)
    mkey = df["step"].dt.to_period("M")
    imp_m_after = (imp_after_series).groupby(mkey).sum()
    pv2load_m   = df.get("pv2load_kWh", pd.Series(0, index=df.index)).astype(float).groupby(mkey).sum()
    exp_paid_m  = df.get("pv_export_paid_kWh", pd.Series(0, index=df.index)).astype(float).groupby(mkey).sum()
    exp_unpd_m  = (df.get("pv_export_kWh", exp_paid_m) - df.get("pv_export_paid_kWh", pd.Series(0, index=df.index)).astype(float)).groupby(mkey).sum()

    fig, ax = plt.subplots(figsize=(5.4,3.2))
    bottom = np.zeros(len(imp_m_after))
    idx = np.arange(len(imp_m_after))
    months = imp_m_after.index.astype(str).tolist()
    for series, label in [(pv2load_m, "Eigenverbrauch"),
                          (imp_m_after, "Netzbezug"),
                          (exp_paid_m, "Rückspeisung bezahlt"),
                          (exp_unpd_m, "Rückspeisung unbezahlt")]:
        vals = series.reindex(imp_m_after.index).values
        ax.bar(idx, vals, bottom=bottom, label=label, alpha=0.95)
        bottom += vals
    ax.set_xticks(idx, months, rotation=45, ha="right")
    ax.set_ylabel("kWh / Monat")
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    ax.legend(fontsize=8, ncols=2)
    images["energy_split"] = _b64(fig)

    # Import monthly before/after
    imp_m_before = ((cons - pv).clip(lower=0)).groupby(mkey).sum()
    fig, ax = plt.subplots(figsize=(5.4,3.2))
    x = np.arange(len(imp_m_before)); width = 0.38
    ax.bar(x-width/2, imp_m_before.values, width, label="ohne Batterie")
    ax.bar(x+width/2, imp_m_after.reindex(imp_m_before.index).values, width, label="mit Batterie")
    ax.set_xticks(x, imp_m_before.index.astype(str).tolist(), rotation=45, ha="right")
    ax.set_ylabel("Netzbezug [kWh / Monat]")
    ax.legend()
    ax.grid(True, axis="y", linestyle="--", alpha=0.5)
    images["import_monthly"] = _b64(fig)

        # ───────────────────────────────────────────────── Cashflow (links: Plot) ──────────────────────────────────────────
    if "cashflows_undisc" in out and out["cashflows_undisc"]:
        yearly = list(map(float, out["cashflows_undisc"]))
    else:
        yearly = [-capex_total] + [annual_net_benefit for _ in range(lifetime)]

    xs  = np.arange(len(yearly))
    cum = np.cumsum(yearly)

    fig, ax = plt.subplots(figsize=(5.6, 3.2))
    width = 0.38
    ax.bar(xs - width/2, yearly, width, label="Jährlicher Cash Flow")
    ax.bar(xs + width/2, cum,   width, label="Kumulierter Cash Flow")

    # Wenige X-Ticks → kein Überlappen
    tick_step = max(1, len(xs)//10)  # ~max 10 Ticks
    ax.set_xticks(xs[::tick_step], [f"Y{i}" for i in xs][::tick_step])

    ax.axhline(0, linewidth=1)
    ax.set_ylabel("CHF")
    ax.set_title("Cashflow-Entwicklung")
    ax.grid(True, axis="y", linestyle="--", alpha=0.35)
    ax.legend()

    if dpb is not None:
        ax.axvline(dpb, linestyle="--")
        ax.text(dpb + 0.1, ax.get_ylim()[1]*0.9, f"Payback ≈ Jahr {int(dpb)}", va="top", fontsize=9)

    images["cashflow_bars"] = _b64(fig)

    # ───────────────────────────────────────────── Werte-Panel (rechts: Tabelle als HTML) ─────────────────────────────
    def _fmt_chf(v):
        try:
            return f"{float(v):,.0f} CHF"
        except Exception:
            return str(v)

    rows_html = []
    for i, (y, c) in enumerate(zip(yearly, cum)):
        rows_html.append(f"<tr><td>Y{i}</td><td class='num'>{_fmt_chf(y)}</td><td class='num'>{_fmt_chf(c)}</td></tr>")

    cashflow_values_html = (
        "<div class='scroll'>"
        "<table class='tbl'>"
        "<thead><tr><th>Jahr</th><th>jährlich</th><th>kumuliert</th></tr></thead>"
        "<tbody>"
        + "".join(rows_html) +
        "</tbody></table></div>"
    )


    # Quarterly plots (daily max)
    quarters = [("Q1", ("01-01","03-31")), ("Q2", ("04-01","06-30")), ("Q3", ("07-01","09-30")), ("Q4", ("10-01","12-31"))]
    for qname, (mmdd_s, mmdd_e) in quarters:
        start = pd.Timestamp(f"{df['step'].dt.year.min()}-{mmdd_s}", tz=tz)
        end   = pd.Timestamp(f"{df['step'].dt.year.max()}-{mmdd_e} 23:59:59", tz=tz)
        mask  = (df["step"]>=start) & (df["step"]<=end)
        s = df.loc[mask, "step"]
        bef = ((cons - pv).clip(lower=0)/step_hours).loc[mask].groupby(s.dt.floor("D")).max()
        aft = (imp_after_series.clip(lower=0)/step_hours).loc[mask].groupby(s.dt.floor("D")).max()
        fig, ax = plt.subplots(figsize=(5.4,3.2))
        # ~120 Marker pro Quartal (bei sehr vielen Tagen sonst zu dicht)
        n = len(bef)
        mev = max(1, n // 120)

        ax.plot(
            bef.index, bef.values, label="ohne Batterie",
            marker=".", markersize=2.5, linewidth=0.8, markevery=mev
        )
        ax.plot(
            aft.index, aft.values, label="mit Batterie",
            marker=".", markersize=2.5, linewidth=0.8, markevery=mev
        )
        ax.xaxis.set_major_locator(mdates.MonthLocator())                  # 1 Tick pro Monat
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))        # z.B. 2024-01
        for lbl in ax.get_xticklabels():
            lbl.set_rotation(45)
            lbl.set_ha("right")
        ax.margins(x=0.01)
        ax.set_ylabel("kW (Tagesmax)")
        ax.set_title(f"Tagespeaks ohne/mit Batterie – {qname}")
        ax.grid(True, linestyle="--", alpha=0.4)
        ax.legend()
        images[f"quarter_{qname}"] = _b64(fig)

    # HTML
    def card(title, value, suffix=""):
        return f'<div class="card"><div class="card-title">{title}</div><div class="card-value">{value}{suffix}</div></div>'

    css = """
    <style>
      :root { --gap: 16px; }
      body { font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 22px; color:#0b1220; }
      h1 { margin: 0 0 10px 0; font-size: 26px; }
      h2 { margin: 20px 0 8px 0; font-size: 18px; }
      .twocol { display: grid; grid-template-columns: 1fr 1fr; gap: var(--gap); }
      .cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--gap); }
      .card { background:#fafbff; border:1px solid #e8ecf3; border-radius:12px; padding:10px 12px; }
      .card-title { font-size:11px; color:#5b6474; text-transform: uppercase; letter-spacing:.04em; }
      .card-value { font-size:18px; font-weight:600; margin-top:6px; }
      figure { margin: 6px 0 0 0; }
      figure img { width: 100%; border:1px solid #e8ecf3; border-radius:12px; }
      figcaption { font-size:12px; color:#5b6474; margin-top:4px; }
      .section { margin-bottom: 18px; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size:12px; }
      .scroll { max-height: 280px; overflow:auto; border:1px solid #e8ecf3; border-radius:8px; padding:6px; background:#fff; }
      .tbl { width:100%; border-collapse:collapse; font-size:12px; }
      .tbl th, .tbl td { padding:6px 8px; border-bottom:1px solid #e8ecf3; }
      .tbl th { text-align:left; color:#5b6474; font-weight:600; }
      .tbl td.num { text-align:right; font-variant-numeric: tabular-nums; }

    </style>
    """
    html = [css, "<h1>Speicher-Optimierung – EV & LSK Ergebnisreport</h1>"]

    econ_cards = [
        card("Capex Batterie", f"{_safe_float(econ.get('capex_battery_chf',0)):,.0f}", " CHF"),
        card("Capex Installation", f"{_safe_float(econ.get('capex_installation_chf',0)):,.0f}", " CHF"),
        card("Opex jährlich", f"{_safe_float(econ.get('opex_annual_chf',0)):,.0f}", " CHF"),
        card("Laufzeit", f"{lifetime}", " Jahre"),
        card("Diskontsatz", f"{dr*100:.1f}", " %"),
        card("Subvention upfront", f"{_safe_float(econ.get('subsidy_upfront_chf',0)):,.0f}", " CHF"),
        card("Demand-Tarif", f"{dc_rate:.0f}", " CHF/kW·Monat"),
        card("Importpreis", f"{import_rate:.2f}", " CHF/kWh"),
    ]
    storage_cards = [
        card("Speicher-Kapazität", f"{_safe_float(storage.get('capacity_kwh',0)):.1f}", " kWh"),
        card("P_charge", f"{_safe_float(storage.get('p_charge_kw',0)):.1f}", " kW"),
        card("P_discharge", f"{_safe_float(storage.get('p_discharge_kw',0)):.1f}", " kW"),
        card("Roundtrip η", f"{_safe_float(storage.get('roundtrip_eff', out.get('roundtrip_eff',0.92)))*100:.0f}", " %"),
        card("SoC min/max", f"{_safe_float(storage.get('soc_min',0))*100:.0f}% / {_safe_float(storage.get('soc_max',1))*100:.0f}%"),
        card("Start-SoC", f"{_safe_float(storage.get('soc0',0.5))*100:.0f}", " %"),
        card("Vergütung (Feed-in)", f"{_safe_float(prices.get('feed_in_chf_per_kWh',0.0)):.2f}", " CHF/kWh"),
        card("Zeit-Setup", f"{tz} · {step_seconds//60}min Step"),
    ]
    html += ['<div class="section"><h2>Annahmen (aus YAML)</h2><div class="cards">', *econ_cards, *storage_cards, '</div></div>']

    kpi_cards = [card(k, v) for k, v in kpi.items()]
    html += ['<div class="section"><h2>KPIs</h2><div class="cards">', *kpi_cards, '</div></div>']

    html += ['<div class="section"><h2>Eigenverbrauch & Autarkie</h2><div class="twocol">',
             f'<figure><img src="data:image/png;base64,{images["evq"]}"><figcaption>Eigenverbrauchsquote (vor/nach)</figcaption></figure>',
             f'<figure><img src="data:image/png;base64,{images["autarkie"]}"><figcaption>Autarkie (vor/nach)</figcaption></figure>',
             '</div></div>']

    html += ['<div class="section"><div class="twocol">',
             f'<figure><img src="data:image/png;base64,{images["energy_split"]}"><figcaption>Energieströme (nach Speicher, monatlich)</figcaption></figure>',
             f'<figure><img src="data:image/png;base64,{images["import_monthly"]}"><figcaption>Netzimport vor/nach (monatlich)</figcaption></figure>',
             '</div></div>']

    html += ['<div class="section"><h2>Lastspitzen & Dauerlinie</h2><div class="twocol">',
             f'<figure><img src="data:image/png;base64,{images["peaks_monthly"]}"><figcaption>Monats-Peaks vor/nach</figcaption></figure>',
             f'<figure><img src="data:image/png;base64,{images["duration_curve"]}"><figcaption>Dauerlinie Netto-Last (vor/nach)</figcaption></figure>',
             '</div></div>']

    html += ['<div class="section"><h2>Finanzen</h2><div class="twocol">']
    # linke Spalte: Plot
    html += [f'<figure><img src="data:image/png;base64,{images["cashflow_bars"]}">'
             f'<figcaption>Cashflow – jährlich & kumuliert (Payback markiert)</figcaption></figure>']
    # rechte Spalte: Werte-Panel als HTML
    html += [cashflow_values_html]
    html += ['</div></div>']


    html += ['<div class="section"><h2>Lastverlauf pro Quartal (Tagesmax, ohne/mit Batterie)</h2><div class="twocol">',
             f'<figure><img src="data:image/png;base64,{images["quarter_Q1"]}"><figcaption>Q1</figcaption></figure>',
             f'<figure><img src="data:image/png;base64,{images["quarter_Q2"]}"><figcaption>Q2</figcaption></figure>',
             '</div></div>']

    html += ['<div class="section"><div class="twocol">',
             f'<figure><img src="data:image/png;base64,{images["quarter_Q3"]}"><figcaption>Q3</figcaption></figure>',
             f'<figure><img src="data:image/png;base64,{images["quarter_Q4"]}"><figcaption>Q4</figcaption></figure>',
             '</div></div>']

    out_slim = {k: v for k, v in out.items() if isinstance(v, (int,float,str)) or k in ("monthly_before","monthly_after")}
    html += ['<div class="section"><h2>Raw Output (kompakt)</h2><pre class="mono">', json.dumps(out_slim, indent=2, ensure_ascii=False), '</pre></div>']

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(html), encoding="utf-8")
