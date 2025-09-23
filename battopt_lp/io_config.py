from __future__ import annotations
from typing import Tuple, Dict, Any
import pandas as pd
import yaml
import numpy as np

# ---------------- Basics ----------------

def read_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# ---------------- CSV Reader (robust) ----------------

def _read_seconds_csv(path: str) -> pd.Series | None:
    """
    Liest Dateien wie:
      #Kommentar...
      #Zeit [s];Verbrauch [kWh oder kW]
      0;4.65
      900;4.35
      ...
    Gibt Series zurück mit Index=Sekunden (float) und Werten=float.
    """
    try:
        df = pd.read_csv(
            path,
            sep=";",
            comment="#",
            header=None,
            engine="python",
        )
    except Exception:
        return None

    if df.shape[1] == 0:
        return None
    if df.shape[1] == 1:
        # Nur eine Spalte -> Werte
        vals = pd.to_numeric(df.iloc[:, 0], errors="coerce")
        s = pd.Series(vals.values, index=pd.RangeIndex(len(vals)), name="kWh")
        return s.dropna()

    # Mind. 2 Spalten: [sec, value]
    sec = pd.to_numeric(df.iloc[:, 0], errors="coerce")
    val = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    ser = pd.Series(val.values, index=sec.values, name="kWh")
    return ser.dropna()

def _read_generic_csv(path: str) -> pd.Series:
    """
    Fallback: liest verschiedenste CSVs.
    - Versucht zuerst Sekunden-Layout.
    - Sonst: nimmt die letzte numerische Spalte als Werte.
    - Index: falls erste Spalte als Datum interpretierbar -> DatetimeIndex,
             sonst RangeIndex.
    """
    s = _read_seconds_csv(path)
    if s is not None and len(s) > 0:
        return s.astype("float64")

    # Fallback: Standard-CSV
    df = pd.read_csv(path)

    # numerische Spalte für Werte wählen
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not num_cols:
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    val_col = num_cols[-1] if num_cols else df.columns[-1]
    vals = pd.to_numeric(df[val_col], errors="coerce")

    # Versuche Datetime in der ersten Spalte
    idx = None
    if df.shape[1] >= 2:
        first = df.columns[0]
        try:
            idx_try = pd.to_datetime(df[first], errors="coerce", utc=False)
            if idx_try.notna().sum() == len(vals):
                idx = idx_try
        except Exception:
            idx = None

    if idx is not None:
        ser = pd.Series(vals.values, index=idx, name="kWh")
    else:
        ser = pd.Series(vals.values, index=pd.RangeIndex(len(vals)), name="kWh")
    return ser.dropna().astype("float64")

# ---------------- Public loader ----------------

def load_timeseries_from_config(cfg: Dict[str, Any]) -> Tuple[pd.Series, pd.Series, float, str | None]:
    """
    Lädt Verbrauch und PV. Unterstützt:
    - Sekunden-CSV (dein Format)
    - generische CSV (optional mit Timestamp-Spalte)
    Ergänzt optional DatetimeIndex, wenn 'start_datetime' in YAML gesetzt ist.
    Gibt (cons, pv, step_hours, tz) zurück.
    """
    ts = (cfg.get("timeseries") or cfg.get("ts") or {})
    cons_path = ts.get("consumption_csv")
    pv_path   = ts.get("pv_csv")
    if not cons_path or not pv_path:
        raise ValueError("timeseries.consumption_csv und timeseries.pv_csv sind Pflicht.")

    cons = _read_generic_csv(cons_path)
    pv   = _read_generic_csv(pv_path)

    # Länge angleichen (min)
    n = min(len(cons), len(pv))
    cons = pd.Series(cons.iloc[:n].to_numpy(dtype="float64"), index=cons.index[:n], name="kWh")
    pv   = pd.Series(pv.iloc[:n].to_numpy(dtype="float64"), index=pv.index[:n],   name="kWh")

    # Schrittweite bestimmen
    step_seconds_cfg = ts.get("step_seconds", None)
    step_seconds_inf = None
    idx = cons.index

    # Wenn Sekundenindex (float/int) vorhanden, Schritt aus Differenzen ermitteln
    if (pd.api.types.is_integer_dtype(idx) or pd.api.types.is_float_dtype(idx)) and len(cons) > 1:
        diffs = pd.Series(idx).diff().dropna()
        if len(diffs) > 0:
            step_seconds_inf = float(diffs.mode().iloc[0])

    step_seconds = float(step_seconds_cfg if step_seconds_cfg is not None else (step_seconds_inf if step_seconds_inf is not None else 900.0))
    step_hours = step_seconds / 3600.0

    # Optional DatetimeIndex synthetisieren, wenn start_datetime gesetzt ist
    start = ts.get("start_datetime", None)
    tz = ts.get("tz", None)

    def _force_datetime(s: pd.Series) -> pd.Series:
        if isinstance(s.index, pd.DatetimeIndex):
            # ggf. TZ ergänzen
            if tz and s.index.tz is None:
                return s.tz_localize(tz)
            return s
        # synthetisieren
        idx_dt = pd.date_range(
            start=start,
            periods=len(s),
            freq=pd.to_timedelta(step_seconds, unit="s"),
            tz=tz,
        )
        return pd.Series(s.values, index=idx_dt, name=s.name)

    if start:
        cons = _force_datetime(cons)
        pv   = _force_datetime(pv)
    else:
        # kein DatetimeIndex -> RangeIndex für eine saubere, dichte Indexierung
        cons.index = pd.RangeIndex(len(cons))
        pv.index   = pd.RangeIndex(len(pv))

    return cons.astype("float64"), pv.astype("float64"), float(step_hours), tz

# ---------------- Baseline ----------------

def baseline_from_profiles(cons: pd.Series, pv: pd.Series) -> Dict[str, float]:
    """
    Baseline ohne Speicher.
    """
    surplus = (pv - cons).clip(lower=0)
    import_ = (cons - pv).clip(lower=0)
    SC0 = float(cons.sum() - import_.sum())
    return {
        "pv_total_kWh": float(pv.sum()),
        "load_total_kWh": float(cons.sum()),
        "self_consumption_no_storage_kWh": float(SC0),
        "feed_in_no_storage_kWh": float(surplus.sum()),
        "import_no_storage_kWh": float(import_.sum()),
    }
